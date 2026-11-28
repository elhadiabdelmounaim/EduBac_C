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
class BaseDevoirs(TestCase):
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
        data = {'titre': 'DM 3 — Produit scalaire', 'consigne': 'Exercices 1 à 3', 'rendu_en_ligne': '1',
                'date_limite': '2030-12-01T08:00', 'classes': [c.pk for c in classes]}
        data.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('devoirs:creer'), data)

    def preparer(self, **fichier):
        self.creer([self.a], fichiers=[pdf()])
        devoir = Devoir.objects.get()
        correction = FichierDevoir.objects.create(
            devoir=devoir, fichier=pdf('correction.pdf'), nom='correction.pdf', taille=15, **fichier)
        return devoir, devoir.fichiers.get(nom='enonce.pdf'), correction


class DevoirsTests(BaseDevoirs):
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
        self.assertIn('01/12/2030', n.message)

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


class RendusTests(BaseDevoirs):
    """Travail rendu par l'élève, correction, rappels, ouverture à date, tableau de bord."""

    def devoir(self, **extra):
        self.creer([self.a, self.b], **extra)
        Notification.objects.all().delete()
        return Devoir.objects.latest('pk')

    def rendre(self, devoir, eleve, *fichiers):
        self.connecter(eleve)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('devoirs:rendre', args=[devoir.pk]), {'pages': list(fichiers)})

    def photo(self, nom='page1.jpg'):
        return SimpleUploadedFile(nom, b'\xff\xd8\xff jpeg', content_type='image/jpeg')

    def test_l_eleve_rend_complete_puis_le_professeur_corrige(self):
        from .models import RenduDevoir
        devoir = self.devoir()
        self.rendre(devoir, self.eleve_a, self.photo('p1.jpg'), self.photo('p2.jpg'))
        rendu = RenduDevoir.objects.get()
        self.assertEqual(rendu.fichiers.count(), 2)
        self.assertFalse(rendu.en_retard)
        prof = Notification.objects.get(recipient=self.prof)
        self.assertEqual(prof.type, 'devoir_rendu')
        self.assertIn('a rendu', prof.message)
        # Compléter : la notification du professeur est regroupée.
        self.rendre(devoir, self.eleve_a, pdf('p3.pdf'))
        self.assertEqual(rendu.fichiers.count(), 3)
        self.assertEqual(Notification.objects.filter(recipient=self.prof).count(), 1)
        # Le professeur voit la copie et corrige.
        self.connecter(self.prof)
        page = self.client.get(reverse('devoirs:rendus', args=[devoir.pk]))
        self.assertContains(page, 'p1.jpg')
        self.assertContains(page, 'Non rendu')            # l'élève de 1bac2
        page_fichier = rendu.fichiers.first()
        self.assertEqual(self.client.get(reverse('devoirs:fichier_rendu', args=[page_fichier.pk])).status_code, 200)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('devoirs:rendus', args=[devoir.pk]),
                             {'rendu': rendu.pk, 'note': '15,5', 'commentaire': 'Bien rédigé.'})
        rendu.refresh_from_db()
        self.assertEqual(str(rendu.note), '15.50')
        self.assertIsNotNone(rendu.corrige_le)
        n = Notification.objects.get(recipient=self.eleve_a, title='Devoir corrigé')
        self.assertIn('15,5/20', n.message)
        # Corrigé : l'élève ne peut plus rien changer.
        self.rendre(devoir, self.eleve_a, self.photo('p4.jpg'))
        self.assertEqual(rendu.fichiers.count(), 3)
        self.connecter(self.eleve_a)
        self.client.post(reverse('devoirs:retirer_page', args=[page_fichier.pk]))
        self.assertTrue(rendu.fichiers.filter(pk=page_fichier.pk).exists())
        page = self.client.get(reverse('devoirs:detail', args=[devoir.pk]))
        self.assertContains(page, '15,5/20')
        self.assertContains(page, 'Bien rédigé.')

    def test_note_invalide_refusee(self):
        from .models import RenduDevoir
        devoir = self.devoir()
        self.rendre(devoir, self.eleve_a, self.photo())
        rendu = RenduDevoir.objects.get()
        self.connecter(self.prof)
        self.client.post(reverse('devoirs:rendus', args=[devoir.pk]), {'rendu': rendu.pk, 'note': '25'})
        rendu.refresh_from_db()
        self.assertIsNone(rendu.corrige_le)

    def test_rendu_en_retard_et_types_refuses(self):
        from .models import RenduDevoir
        devoir = self.devoir(date_limite='2020-01-01T08:00')
        self.rendre(devoir, self.eleve_a, SimpleUploadedFile('x.exe', b'MZ'))
        self.assertFalse(RenduDevoir.objects.exists())
        self.rendre(devoir, self.eleve_a, self.photo())
        self.assertTrue(RenduDevoir.objects.get().en_retard)

    def test_seuls_les_eleves_de_la_classe_rendent_et_voient_les_copies(self):
        from .models import FichierRendu, RenduDevoir
        devoir = self.devoir()
        self.rendre(devoir, self.eleve_x, self.photo())          # autre classe
        self.assertFalse(RenduDevoir.objects.exists())
        self.rendre(devoir, self.eleve_a, self.photo())
        page = FichierRendu.objects.get()
        for user in (self.eleve_b, self.autre_prof):
            self.connecter(user)
            self.assertEqual(self.client.get(reverse('devoirs:fichier_rendu', args=[page.pk])).status_code, 404)
            self.client.post(reverse('devoirs:retirer_page', args=[page.pk]))
        self.assertTrue(FichierRendu.objects.exists())
        self.connecter(self.autre_prof)
        self.assertEqual(self.client.get(reverse('devoirs:rendus', args=[devoir.pk])).status_code, 404)
        # Sans rendu en ligne : rien à déposer.
        Devoir.objects.filter(pk=devoir.pk).update(rendu_en_ligne=False)
        self.assertEqual(self.rendre(devoir, self.eleve_b, self.photo()).status_code, 404)

    def test_retirer_la_derniere_page_annule_le_rendu(self):
        from .models import FichierRendu, RenduDevoir
        devoir = self.devoir()
        self.rendre(devoir, self.eleve_a, self.photo())
        page = FichierRendu.objects.get()
        chemin = Path(page.fichier.path)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('devoirs:retirer_page', args=[page.pk]))
        self.assertFalse(RenduDevoir.objects.exists())
        self.assertFalse(chemin.exists())

    def test_rappel_24h_avant_une_seule_fois_aux_eleves_sans_rendu(self):
        from .services import rappels_devoirs
        devoir = self.devoir(date_limite=timezone.localtime(timezone.now() + timedelta(hours=20)).strftime('%Y-%m-%dT%H:%M'))
        self.rendre(devoir, self.eleve_a, self.photo())
        Notification.objects.all().delete()
        self.assertEqual(rappels_devoirs(), 1)
        self.assertEqual(list(Notification.objects.values_list('recipient__username', flat=True)), ['eb'])
        self.assertEqual(rappels_devoirs(), 0)
        # Rien pour un devoir lointain.
        lointain = self.devoir(date_limite='2031-01-01T08:00')
        self.assertEqual(rappels_devoirs(), 0)
        self.assertIsNone(Devoir.objects.get(pk=lointain.pk).rappel_envoye_le)

    def test_commande_planifiee(self):
        from io import StringIO
        from django.core.management import call_command
        sortie = StringIO()
        call_command('send_quiz_reminders', stdout=sortie)
        self.assertIn('rappel(s) de devoir', sortie.getvalue())

    def test_ouverture_a_date_previent_les_eleves_une_fois(self):
        from .services import ouvertures_automatiques
        devoir, _, correction = self.preparer(verrouille=True, ouverture_le=timezone.now() - timedelta(minutes=5))
        Notification.objects.all().delete()
        self.assertEqual(ouvertures_automatiques(), 1)
        self.assertEqual(list(Notification.objects.values_list('recipient__username', flat=True)), ['ea'])
        self.assertEqual(ouvertures_automatiques(), 0)

    def test_deverrouiller_avec_ou_sans_prevenir(self):
        devoir, enonce, correction = self.preparer(verrouille=True)
        Notification.objects.all().delete()
        self.connecter(self.prof)
        self.client.post(reverse('devoirs:verrou', args=[correction.pk]), {'action': 'deverrouiller'})
        self.assertFalse(Notification.objects.exists())
        self.client.post(reverse('devoirs:verrou', args=[correction.pk]), {'action': 'verrouiller'})
        self.client.post(reverse('devoirs:verrou', args=[correction.pk]), {'action': 'deverrouiller', 'prevenir': '1'})
        self.assertEqual(Notification.objects.get().title, 'Document disponible')

    def test_tableau_de_bord_devoirs_a_rendre(self):
        devoir = self.devoir(date_limite=timezone.localtime(timezone.now() + timedelta(hours=30)).strftime('%Y-%m-%dT%H:%M'))
        self.connecter(self.eleve_a)
        page = self.client.get(reverse('accounts:dashboard'))
        self.assertContains(page, 'Devoirs à rendre')
        self.assertContains(page, reverse('devoirs:detail', args=[devoir.pk]) + '#mon-travail')
        self.rendre(devoir, self.eleve_a, self.photo())
        self.connecter(self.eleve_a)
        self.assertNotContains(self.client.get(reverse('accounts:dashboard')), 'Devoirs à rendre')


PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 40


class AnnotationTests(BaseDevoirs):
    """Correction dessinée sur une page photographiée : calque + page corrigée, original intact."""

    def setUp(self):
        super().setUp()
        self.creer([self.a])
        self.devoir = Devoir.objects.get()
        self.connecter(self.eleve_a)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('devoirs:rendre', args=[self.devoir.pk]), {'pages': [
                SimpleUploadedFile('p1.jpg', b'\xff\xd8\xff jpeg', content_type='image/jpeg'),
                SimpleUploadedFile('p2.pdf', b'%PDF-1.4', content_type='application/pdf')]})
        from .models import FichierRendu
        self.photo = FichierRendu.objects.get(nom='p1.jpg')
        self.pdf = FichierRendu.objects.get(nom='p2.pdf')
        Notification.objects.all().delete()

    def enregistrer(self, page, calque=PNG, annotee=PNG):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('devoirs:annoter', args=[page.pk]), {
                'calque': SimpleUploadedFile('calque.png', calque, content_type='image/png'),
                'annotee': SimpleUploadedFile('corrigee.png', annotee, content_type='image/png')})

    def test_annoter_puis_l_eleve_voit_la_copie_corrigee(self):
        self.connecter(self.prof)
        self.assertContains(self.client.get(reverse('devoirs:rendus', args=[self.devoir.pk])), 'Annoter')
        self.assertEqual(self.client.get(reverse('devoirs:annoter', args=[self.photo.pk])).status_code, 200)
        self.assertEqual(self.enregistrer(self.photo).status_code, 200)
        self.photo.refresh_from_db()
        self.assertTrue(self.photo.annotee and self.photo.calque and self.photo.annote_le)
        self.assertEqual(Notification.objects.get().title, 'Copie corrigée')
        self.enregistrer(self.photo)                       # reprise : pas de seconde notification
        self.assertEqual(Notification.objects.count(), 1)
        url = reverse('devoirs:fichier_rendu', args=[self.photo.pk])
        self.assertEqual(self.client.get(url + '?version=calque').status_code, 200)
        self.connecter(self.eleve_a)
        page = self.client.get(reverse('devoirs:detail', args=[self.devoir.pk]))
        self.assertContains(page, 'p1.jpg — corrigée')
        r = self.client.get(url + '?version=corrigee')
        self.assertEqual(r['Content-Type'], 'image/png')
        self.assertEqual(self.client.get(url + '?version=calque').status_code, 404)    # le calque : professeur seulement
        self.client.post(reverse('devoirs:retirer_page', args=[self.photo.pk]))          # page annotée : on la garde
        self.assertTrue(type(self.photo).objects.filter(pk=self.photo.pk).exists())
        self.assertEqual(b''.join(self.client.get(url).streaming_content), b'\xff\xd8\xff jpeg')   # original intact

    def test_refus(self):
        self.connecter(self.prof)
        self.assertEqual(self.enregistrer(self.photo, calque=b'pas une image').status_code, 400)
        self.assertEqual(self.client.get(reverse('devoirs:annoter', args=[self.pdf.pk])).status_code, 404)
        for user in (self.autre_prof, self.eleve_a):
            self.connecter(user)
            self.enregistrer(self.photo)
        self.photo.refresh_from_db()
        self.assertFalse(self.photo.annotee)

    def test_supprimer_la_page_efface_la_correction(self):
        self.connecter(self.prof)
        self.enregistrer(self.photo)
        self.photo.refresh_from_db()
        chemins = [Path(self.photo.fichier.path), Path(self.photo.calque.path), Path(self.photo.annotee.path)]
        self.assertTrue(all(c.exists() for c in chemins))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('devoirs:supprimer', args=[self.devoir.pk]))
        self.assertFalse(any(c.exists() for c in chemins))
