"""robots.txt et sitemap.xml : seules les pages publiques sont proposées aux moteurs de recherche."""
from django.http import HttpResponse
from django.urls import reverse
from django.utils.xmlutils import SimplerXMLGenerator
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

PRIVATE_PREFIXES = ('/admin/', '/compte/', '/quizzes/', '/classrooms/', '/chat/', '/tableau/',
                    '/notifications/', '/ai/', '/recherche/')


@require_GET
def robots_txt(request):
    lines = ['User-agent: *']
    lines += [f'Disallow: {prefix}' for prefix in PRIVATE_PREFIXES]
    lines.append(f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}")
    return HttpResponse('\n'.join(lines) + '\n', content_type='text/plain; charset=utf-8')


def public_urls():
    from education.curriculum import CURRICULUM
    from education.models import Course, Lesson
    urls = [reverse(name) for name in (
        'education:home', 'education:niveaux', 'education:about', 'education:help', 'education:bac',
        'education:contact', 'education:legal', 'education:privacy', 'education:terms',
        'accounts:register_student',
    )]
    codes = [item['code'] for item in CURRICULUM] if isinstance(CURRICULUM, list) else list(CURRICULUM)
    urls += [reverse('education:niveau_detail', args=[code]) for code in codes]
    urls += [reverse('education:course_detail', args=[pk]) for pk in Course.objects.values_list('pk', flat=True)]
    urls += [reverse('education:lesson_detail', args=[pk])
             for pk in Lesson.objects.order_by('pk').values_list('pk', flat=True)]
    return urls


@require_GET
@cache_page(3600)
def sitemap_xml(request):
    response = HttpResponse(content_type='application/xml; charset=utf-8')
    xml = SimplerXMLGenerator(response, 'utf-8')
    xml.startDocument()
    xml.startElement('urlset', {'xmlns': 'http://www.sitemaps.org/schemas/sitemap/0.9'})
    for url in public_urls():
        xml.startElement('url', {})
        xml.addQuickElement('loc', request.build_absolute_uri(url))
        xml.endElement('url')
    xml.endElement('urlset')
    xml.endDocument()
    return response
