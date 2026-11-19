/* Sur smartphone, la page d'accueil mène une fois par session à l'écran
   « Bienvenue » (/bienvenue/). Le bureau, les robots et les navigations
   internes suivantes ne sont pas concernés ; le drapeau est posé avant la
   redirection, donc aucune boucle n'est possible. */
(function () {
    var script = document.currentScript;
    try {
        if (!window.matchMedia || !window.matchMedia('(max-width: 767.98px)').matches) return;
        if (navigator.webdriver || /bot|crawl|spider|slurp|lighthouse|preview/i.test(navigator.userAgent)) return;
        if (sessionStorage.getItem('edubac-welcome')) return;
        sessionStorage.setItem('edubac-welcome', '1');
        if (sessionStorage.getItem('edubac-welcome') !== '1') return;
        var target = script && script.getAttribute('data-welcome-url');
        if (!target) return;
        location.replace(target);
    } catch (e) { /* stockage indisponible : on reste sur l'accueil */ }
})();
