// main.js

function initHeroSlider() {
    const slides = document.querySelectorAll('.hero-slide');
    if (slides.length === 0) return;

    let current = 0;

    setInterval(() => {
        // 1. Identify current, next, and previous
        const prevSlide = slides[current];
        current = (current + 1) % slides.length;
        const nextSlide = slides[current];

        // 2. Clear old 'prev' classes
        slides.forEach(s => s.classList.remove('prev'));

        // 3. Set the current one to 'prev' (slides it slightly left)
        prevSlide.classList.remove('active');
        prevSlide.classList.add('prev');

        // 4. Set the next one to 'active' (slides it in from right)
        nextSlide.classList.add('active');
    }, 5000); 
}
	
	
function arrangeCircle(containerId, radius) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const items = container.children;
    const total = items.length;
    
    // Use radius to define center
    const centerX = radius; 
    const centerY = radius;

    for (let i = 0; i < total; i++) {
        const angle = (i / total) * (2 * Math.PI) - (Math.PI / 2);
        const x = centerX + radius * Math.cos(angle) - 25; 
        const y = centerY + radius * Math.sin(angle) - 25;

        items[i].style.left = `${x}px`;
        items[i].style.top = `${y}px`;
        
        if (containerId === 'categories') {
            items[i].style.animation = 'none';
        }
    }
}



class AutoCarousel {
    constructor(track, options = {}) {
        this.track = track;
        this.cards = Array.from(track.children);
        if (this.cards.length === 0) return;

        this.settings = {
            interval: options.interval || 3000,
            transitionTime: options.transitionTime || 600,
            gap: options.gap || 24
        };

        this.index = 0;
        this.cardWidth = this.cards[0].offsetWidth + this.settings.gap;
        this.timer = null;

        // Drag + momentum
        this.isDragging = false;
        this.startX = 0;
        this.currentTranslate = 0;
        this.prevTranslate = 0;
        this.velocity = 0;
        this.lastX = 0;
        this.lastTime = 0;

        this.prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        this.init();
    }

    init() {
        // Clone for infinite loop
        this.cards.forEach(card => {
            this.track.appendChild(card.cloneNode(true));
        });

        if (!this.prefersReducedMotion) {
            this.start();
        }

        this.bindHoverFocus();
        this.bindDrag();
        this.bindWheel();
    }

    start() {
        if (this.timer || this.prefersReducedMotion) return;
        this.timer = setInterval(() => this.move(), this.settings.interval);
    }

    stop() {
        clearInterval(this.timer);
        this.timer = null;
    }

    move() {
        this.index++;
        this.setTranslate(-this.index * this.cardWidth, true);

        if (this.index >= this.cards.length) {
            setTimeout(() => {
                this.track.style.transition = 'none';
                this.index = 0;
                this.setTranslate(0, false);
                this.track.offsetHeight;
                this.track.style.transition = `transform ${this.settings.transitionTime}ms ease`;
            }, this.settings.transitionTime);
        }
    }

    setTranslate(value, animate = true) {
        if (animate && !this.prefersReducedMotion) {
            this.track.style.transition = `transform ${this.settings.transitionTime}ms ease`;
        } else {
            this.track.style.transition = 'none';
        }

        this.track.style.transform = `translateX(${value}px)`;
        this.currentTranslate = value;
    }

    bindHoverFocus() {
        const container = this.track.parentElement;
        container.setAttribute('tabindex', '0');
        container.addEventListener('mouseenter', () => this.stop());
        container.addEventListener('mouseleave', () => this.start());
        container.addEventListener('touchstart', () => this.stop(), { passive: true });
        container.addEventListener('touchend', () => this.start());
        container.addEventListener('focusin', () => this.stop());
        container.addEventListener('focusout', () => this.start());
    }

    bindDrag() {
        const container = this.track.parentElement;
        const startDrag = (x) => {
            this.isDragging = true;
            this.startX = x;
            this.prevTranslate = this.currentTranslate;
            this.velocity = 0;
            this.lastX = x;
            this.lastTime = performance.now();
            this.stop();
            this.track.style.transition = 'none';
        };

        const moveDrag = (x) => {
            if (!this.isDragging) return;
            const now = performance.now();
            const dx = x - this.lastX;
            const dt = now - this.lastTime;
            this.velocity = dx / dt;
            this.lastX = x;
            this.lastTime = now;
            this.currentTranslate = this.prevTranslate + (x - this.startX);
            this.track.style.transform = `translateX(${this.currentTranslate}px)`;
        };

        const endDrag = () => {
            if (!this.isDragging) return;
            this.isDragging = false;
            const momentum = this.velocity * 300;
            this.currentTranslate += momentum;
            this.index = Math.round(Math.abs(this.currentTranslate) / this.cardWidth);
            this.setTranslate(-this.index * this.cardWidth, true);
            this.start();
        };

        container.addEventListener('mousedown', e => startDrag(e.pageX));
        window.addEventListener('mousemove', e => moveDrag(e.pageX));
        window.addEventListener('mouseup', endDrag);
        container.addEventListener('touchstart', e => startDrag(e.touches[0].pageX), { passive: true });
        container.addEventListener('touchmove', e => moveDrag(e.touches[0].pageX), { passive: true });
        container.addEventListener('touchend', endDrag);
    }

    bindWheel() {
        const container = this.track.parentElement;
        container.addEventListener('wheel', e => {
            if (Math.abs(e.deltaY) < Math.abs(e.deltaX)) return;
            e.preventDefault();
            this.stop();
            this.currentTranslate -= e.deltaY;
            this.track.style.transition = 'none';
            this.track.style.transform = `translateX(${this.currentTranslate}px)`;

            clearTimeout(this.wheelTimeout);
            this.wheelTimeout = setTimeout(() => {
                this.index = Math.round(Math.abs(this.currentTranslate) / this.cardWidth);
                this.setTranslate(-this.index * this.cardWidth, true);
                this.start();
            }, 150);
        }, { passive: false });
    }
}

document.addEventListener("DOMContentLoaded", () => {

	// 0--- HERO BACKGROUND CAROUSEL ---
    initHeroSlider();

    // 1. CIRCULAR ROTARY LAYOUT
    const isMobile = window.innerWidth <= 768;
    setTimeout(() => {
        // --- CATEGORIES LOGIC ---
        // On desktop, radius is 130. 
        // On mobile, we push them to 160 so they sit outside the 240px disc
        const categoryRadius = isMobile ? 160 : 130;
        arrangeCircle('categories', categoryRadius); 
        
        // --- SUPPLIERS LOGIC ---
        if (!isMobile) {
            arrangeCircle('suppliers', 240);
        } else {
            const supps = document.getElementById('suppliers');
            if(supps) supps.style.display = 'none';
        }
    }, 200);

    // 2. CAROUSEL INITIALIZATION
    document.querySelectorAll('.cards-container').forEach(track => {
        if (track.children.length > 0) {
            const customGap = (track.id === 'suppliers-mobile-track') ? 20 : 24;
            new AutoCarousel(track, {
                interval: 3000,
                transitionTime: 600,
                gap: customGap
            });
        }
    });

    // 3. UNIVERSAL CLICK HANDLER (RESTORED)
    // This makes the brand filtering work again
    document.querySelectorAll('.supplier-link, .mobile-supplier-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const brand = link.getAttribute('data-supplier');
            if (brand) {
                console.log("Filtering by brand:", brand);
                alert("Loading products from: " + brand.toUpperCase());
            }
        });
    });
    
    

    // 4. NAVIGATION & HAMBURGER
   
    const hamburger = document.getElementById('navHamburger');
    const hamIcon = hamburger ? hamburger.querySelector('i') : null;
    const navLinks = document.querySelector('.nav-links');
    const navItems = document.querySelectorAll('.nav-item');

    if (hamburger && navLinks) {
        hamburger.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const isActive = navLinks.classList.toggle('active');
            
            // Toggle Icon Bars -> X
            if (hamIcon) {
                if (isActive) {
                    hamIcon.classList.replace('fa-bars', 'fa-xmark');
                } else {
                    hamIcon.classList.replace('fa-xmark', 'fa-bars');
                }
            }
        });
    }

    // Dropdowns
    navItems.forEach(item => {
        const link = item.querySelector('a');
        const dropdown = item.querySelector('.dropdown');

        if (dropdown && link) {
            link.addEventListener('click', (e) => {
                if (window.innerWidth <= 480) {
                    e.preventDefault();
                    e.stopPropagation();
                    
                    // Close other sub-menus
                    navItems.forEach(other => {
                        if (other !== item) other.classList.remove('open');
                    });
                    item.classList.toggle('open');
                }
            });
        }
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
        if (navLinks && !navLinks.contains(e.target) && hamburger && !hamburger.contains(e.target)) {
            navLinks.classList.remove('active');
            if (hamIcon) hamIcon.classList.replace('fa-xmark', 'fa-bars');
            navItems.forEach(item => item.classList.remove('open'));
        }
    });

    // 6. SHOPPING CART ALERTS
    document.querySelectorAll('.add-btn').forEach(button => {
        button.addEventListener('click', () => {
            const productInfo = button.closest('.product-info');
            const productName = productInfo?.querySelector('.product-name')?.innerText || "Item";
            alert(productName + ' added to cart!');
        });
    });

    // 7. UI CLEANUP ON RESIZE
    window.addEventListener('resize', () => {
        if (window.innerWidth > 480) {
            document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
        }
    });
});
