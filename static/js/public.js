document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('publicNavToggle');
    const links = document.getElementById('publicNavLinks');
    const year = document.getElementById('copyrightYear');

    year.textContent = String(new Date().getFullYear());

    const closeNavigation = () => {
        links.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-label', 'Open navigation');
        toggle.innerHTML = '<i class="fas fa-bars" aria-hidden="true"></i>';
    };

    toggle.addEventListener('click', () => {
        const isOpen = links.classList.toggle('is-open');
        toggle.setAttribute('aria-expanded', String(isOpen));
        toggle.setAttribute('aria-label', isOpen ? 'Close navigation' : 'Open navigation');
        toggle.innerHTML = `<i class="fas fa-${isOpen ? 'xmark' : 'bars'}" aria-hidden="true"></i>`;
    });

    links.querySelectorAll('a').forEach(link => {
        link.addEventListener('click', closeNavigation);
    });

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeNavigation();
    });

    const revealElements = document.querySelectorAll('.reveal');
    if (!('IntersectionObserver' in window) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        revealElements.forEach(element => element.classList.add('is-visible'));
        return;
    }

    const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
        });
    }, { threshold: 0.12 });
    revealElements.forEach(element => observer.observe(element));
});
