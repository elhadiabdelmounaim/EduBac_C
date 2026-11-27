"""Devoirs : création pour une ou plusieurs classes, fichiers visibles ou verrouillés (à la main ou
jusqu'à une date), accès des élèves limité à leurs classes, notifications, suppression."""
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from classrooms.models import Classroom, ClassroomMember
from notifications.models import Notification

from .models import Devoir, FichierDevoir

MEDIA = tempfile.mkdtemp(prefix='edubac-devoirs-tests-')


def pdf(nom='enonce.pdf', contenu=b'%PDF-1.4 devoir'):
    return SimpleUploadedFile(nom, contenu, content_type='application/pdf')


@override_settings(MEDIA_ROOT=MEDIA, ALLOWED_HOSTS=['testserver'])
class DevoirsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.prof = User.objects.create_user(username='prof', email='prof@example.test', role='teacher')
        self.autre_prof = User.objects.create_user(username='prof2', email='prof2@example.test', role='teacher')
        self.a = Classroom.objects.create(name='1bac1', niveau='1ere_bac_sc', teacher=self.prof)
        self.b = Classroom.objects.create(name='1bac2', niveau='1ere_bac_sc', teacher=self.prof)
        self.etrangere = Classroom.objects.create(name='Autre', niveau='1ere_bac_sc', teacher=self.autre_prof)
        self.eleve_a = self.eleve('ea', self.a)
        self.eleve_b = self.eleve('eb', self.b)
        self.eleve_x = self.eleve('ex', self.etrangere)

    def eleve(self, nom, classe):
        user = User.objects.create_user(username=nom, email=f'{nom}@example.test', role='student')
        ClassroomMember.objects.create(classroom=classe, user=user)
        return user

    def connecter(self, user):
        session = self.client.session
        session['user_id'] = user.pk
        session.save()

    def creer(self, classes, **extra):
        self.connecter(self.prof)
        data = {'titre': 'DM 3 — Produit scalaire', 'consigne': 'Exercices 1 à 3',
                'date_limite': '2026-12-01T08:00', 'classes': [c.pk for c in classes]}
        data.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('devoirs:creer'), data)

    # ---------- Création ----------
    def test_creation_pour_deux_classes_avec_fichiers_et_notification(self):
        response = self.creer([self.a, self.b], fichiers=[pdf()], fichiers_verrouilles=[pdf('correction.pdf')])
        devoir = Devoir.objects.get()
        self.assertRedirects(response, reverse('devoirs:detail', args=[devoir.pk]), fetch_redirect_response=False)
        self.assertEqual(set(devoir.classes.all()), {self.a, self.b})
        enonce, correction = devoir.fichiers.order_by('pk')
        self.assertFalse(enonce.verrouille)
        self.assertTrue(correction.verrouille)
        self.assertTrue(Path(correction.fichier.path).is_file())
        self.assertNotIn('correction', correction.fichier.name)          # nom imprévisible sur le disque
        notifies = set(Notification.objects.filter(type='devoir').values_list('recipient__username', flat=True))
        self.assertEqual(notifies, {'ea', 'eb'})
        n = Notification.objects.get(recipient=self.eleve_a)
        self.assertEqual(n.link, reverse('devoirs:detail', args=[devoir.pk]))
        self.assertIn('01/12/2026', n.message)

    def test_creation_refusee_sans_classe_ou_classe_d_un_autre(self):
        self.creer([])
        self.creer([self.etrangere])
        self.assertFalse(Devoir.objects.exists())
        self.assertFalse(Notification.objects.filter(type='devoir').exists())

    def test_fichier_refuse_type_ou_taille(self):
        self.creer([self.a], fichiers=[SimpleUploadedFile('virus.exe', b'MZ')])
        self.creer([self.a], fichiers=[SimpleUploadedFile('page.html', b'<script>')])
        self.assertFalse(Devoir.objects.exists())
        from . import services
        ancien = services.TAILLE_MAX
        services.TAILLE_MAX = 10
        try:
            self.creer([self.a], fichiers=[pdf(contenu=b'x' * 11)])
        finally:
            services.TAILLE_MAX = ancien
        self.assertFalse(Devoir.objects.exists())

    def test_eleve_ne_peut_pas_creer(self):
        self.connecter(self.eleve_a)
        self.client.post(reverse('devoirs:creer'), {'titre': 'x', 'classes': [self.a.pk]})
        self.assertFalse(Devoir.objects.exists())

    # ---------- Accès des élèves ----------
    def preparer(self, **fichier):
        self.creer([self.a], fichiers=[pdf()])
        devoir = Devoir.objects.get()
        correction = FichierDevoir.objects.create(
            devoir=devoir, fichier=pdf('correction.pdf'), nom='correction.pdf', taille=15, **fichier)
        return devoir, devoir.fichiers.get(nom='enonce.pdf'), correction

    def test_eleve_voit_les_devoirs_de_sa_classe_seulement(self):
        devoir, enonce, _ = self.preparer(verrouille=True)
        self.connecter(self.eleve_a)
        page = self.client.get(reverse('devoirs:index'))
        self.assertContains(page, 'DM 3 — Produit scalaire')
        self.assertContains(page, 'Disponible plus tard')
        self.assertNotContains(page, 'Nouveau devoir')
        self.assertEqual(self.client.get(reverse('devoirs:telecharger', args=[enonce.pk])).status_code, 200)
        self.connecter(self.eleve_b)
        self.assertNotContains(self.client.get(reverse('devoirs:index')), 'Produit scalaire')
        self.assertRedirects(self.client.get(reverse('devoirs:detail', args=[devoir.pk])), reverse('devoirs:index'))
        self.assertEqual(self.client.get(reverse('devoirs:telecharger', args=[enonce.pk])).status_code, 404)

    def test_visiteur_redirige_vers_la_connexion(self):
        devoir, enonce, _ = self.preparer()
        self.client.logout()
        for url in (reverse('devoirs:index'), reverse('devoirs:detail', args=[devoir.pk]),
                    reverse('devoirs:telecharger', args=[enonce.pk])):
            self.assertRedirects(self.client.get(url), reverse('accounts:login'), fetch_redirect_response=False)

    def test_fichier_verrouille_inaccessible_puis_deverrouille(self):
        devoir, _, correction = self.preparer(verrouille=True)
        url = reverse('devoirs:telecharger', args=[correction.pk])
        self.connecter(self.eleve_a)
        page = self.client.get(reverse('devoirs:detail', args=[devoir.pk]))
        self.assertContains(page, 'correction.pdf')
        self.assertNotContains(page, url)                     # pas de lien
        self.assertRedirects(self.client.get(url), reverse('devoirs:detail', args=[devoir.pk]))
        # Le professeur l'ouvre toujours, et le déverrouille.
        self.connecter(self.prof)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(reverse('devoirs:verrou', args=[correction.pk]), {'action': 'deverrouiller'})
        self.connecter(self.eleve_a)
        reponse = self.client.get(url)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse['Content-Type'], 'application/pdf')
        self.assertEqual(reponse['Cache-Control'], 'private, no-store')
        self.assertEqual(b''.join(reponse.streaming_content), b'%PDF-1.4 devoir')
        self.assertIn('attachment', self.client.get(url + '?telecharger=1')['Content-Disposition'])

    def test_ouverture_automatique_a_la_date(self):
        devoir, _, correction = self.preparer(verrouille=True, ouverture_le=timezone.now() + timedelta(hours=1))
        url = reverse('devoirs:telecharger', args=[correction.pk])
        self.connecter(self.eleve_a)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertContains(self.client.get(reverse('devoirs:detail', args=[devoir.pk])), 'Disponible le')
        FichierDevoir.objects.filter(pk=correction.pk).update(ouverture_le=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_professeur_verrouille_avec_date(self):
        _, enonce, _ = self.preparer()
        self.connecter(self.prof)
        self.client.post(reverse('devoirs:verrou', args=[enonce.pk]),
                         {'action': 'verrouiller', 'ouverture_le': '2030-01-01T10:00'})
        enonce.refresh_from_db()
        self.assertTrue(enonce.verrouille)
        self.assertEqual(timezone.localtime(enonce.ouverture_le).strftime('%Y-%m-%d %H:%M'), '2030-01-01 10:00')
        self.connecter(self.eleve_a)
        self.assertEqual(self.client.get(reverse('devoirs:telecharger', args=[enonce.pk])).status_code, 302)

    # ---------- Gestion ----------
    def test_ajouter_et_retirer_un_fichier(self):
        devoir, enonce, _ = self.preparer()
        self.connecter(self.prof)
        self.client.post(reverse('devoirs:ajouter', args=[devoir.pk]),
                         {'fichiers': [pdf('corrige.pdf')], 'verrouille': '1'})
        corrige = devoir.fichiers.get(nom='corrige.pdf')
        self.assertTrue(corrige.verrouille)
        chemin = Path(enonce.fichier.path)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('devoirs:retirer', args=[enonce.pk]))
        self.assertFalse(FichierDevoir.objects.filter(pk=enonce.pk).exists())
        self.assertFalse(chemin.exists())

    def test_un_autre_professeur_ou_un_eleve_ne_gere_rien(self):
        devoir, enonce, _ = self.preparer()
        for user in (self.autre_prof, self.eleve_a):
            self.connecter(user)
            self.client.post(reverse('devoirs:retirer', args=[enonce.pk]))
            self.client.post(reverse('devoirs:verrou', args=[enonce.pk]), {'action': 'verrouiller'})
            self.client.post(reverse('devoirs:supprimer', args=[devoir.pk]))
            self.client.post(reverse('devoirs:ajouter', args=[devoir.pk]), {'fichiers': [pdf('x.pdf')]})
        self.assertTrue(FichierDevoir.objects.filter(pk=enonce.pk, verrouille=False).exists())
        self.assertEqual(devoir.fichiers.count(), 2)
        self.connecter(self.autre_prof)
        self.assertNotContains(self.client.get(reverse('devoirs:index')), reverse('devoirs:detail', args=[devoir.pk]))
        self.assertEqual(self.client.get(reverse('devoirs:modifier', args=[devoir.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('devoirs:telecharger', args=[enonce.pk])).status_code, 404)

    def test_modifier_ajoute_une_classe_et_previent_ses_eleves_seulement(self):
        self.creer([self.a])
        devoir = Devoir.objects.get()
        Notification.objects.all().delete()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('devoirs:modifier', args=[devoir.pk]), {
                'titre': 'DM 3 (corrigé)', 'consigne': '', 'date_limite': '', 'classes': [self.a.pk, self.b.pk]})
        devoir.refresh_from_db()
        self.assertEqual(devoir.titre, 'DM 3 (corrigé)')
        self.assertIsNone(devoir.date_limite)
        self.assertEqual(set(devoir.classes.all()), {self.a, self.b})
        self.assertEqual(list(Notification.objects.values_list('recipient__username', flat=True)), ['eb'])

    def test_supprimer_le_devoir_et_ses_fichiers(self):
        devoir, enonce, correction = self.preparer()
        chemins = [Path(enonce.fichier.path), Path(correction.fichier.path)]
        self.connecter(self.prof)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('devoirs:supprimer', args=[devoir.pk]))
        self.assertFalse(Devoir.objects.exists())
        self.assertFalse(any(c.exists() for c in chemins))

    def test_navigation_et_recherche(self):
        self.connecter(self.eleve_a)
        page = self.client.get(reverse('devoirs:index'))
        self.assertContains(page, 'class="bn-item" data-nav="devoirs"')
        self.assertContains(page, 'bi-journal-arrow-down')
        self.connecter(self.prof)
        page = self.client.get(reverse('devoirs:index'))
        self.assertContains(page, 'bottom-nav bottom-nav-6')
        self.assertContains(page, 'data-nav="devoirs"')
        donnees = self.client.get(reverse('education:search_quick'), {'q': 'الواجبات'}).json()
        self.assertEqual(donnees['direct'], reverse('devoirs:index'))
