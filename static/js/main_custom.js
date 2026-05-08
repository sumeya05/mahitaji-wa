/**
    * main_custom.js - Custom JavaScript for Mahitaji's interactive features, including:
    * - Chat widget toggle and message handling
    * - Circular icon arrangement with radiating spokes
    * - Hero slider functionality
    * - Auto-scrolling supplier carousel
 */

// Chat Widget Logic




/**
 * arrangeCircle: Mathematically distributes icons and draws radiating spokes.
 * @param {string} containerId - The ID of the container to arrange
 * @param {number} radius - The orbital radius in pixels
 * @param {boolean} drawLines - Whether to draw spokes for this ring
 */

function arrangeCircle(containerId, radius, drawLines = false) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const items = container.children;
    const total = items.length;
    const centerX = 0; 
    const centerY = 0;
    
    // Get or create SVG overlay for spokes
    let svg = document.getElementById('rotary-svg');
    if (!svg) {
        svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("id", "rotary-svg");
        // Viewbox centered at 0,0 to match our JS math
        svg.setAttribute("viewBox", "-400 -400 800 800");
        document.querySelector('.rotary-wrapper').appendChild(svg);
    }

    for (let i = 0; i < total; i++) {
        // Uniform angular distribution
        const angle = (i / total) * (2 * Math.PI) - (Math.PI / 2);
        
        // Icon Positioning: Centered by subtracting half of the 56px icon size (28px)
        const y = centerY + radius * Math.sin(angle) - 45; //category
        const x = centerX + radius * Math.cos(angle) - 45; //supplier
        

        items[i].style.left = `${x}px`;
        items[i].style.top = `${y}px`;

        // Draw Spoke: Lines radiate from 0,0 to the icon's center coordinate
        if (drawLines) {
            const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
            line.setAttribute("x1", 0);
            line.setAttribute("y1", 0);
            line.setAttribute("x2", radius * Math.cos(angle));
            line.setAttribute("y2", radius * Math.sin(angle));
            line.setAttribute("class", containerId === 'categories' ? 'spoke-inner' : 'spoke-outer');
            svg.appendChild(line);
        }
    }
}

function initHeroSlider() {
    const slides = document.querySelectorAll('.hero-slide');
    if (slides.length === 0) return;
    let current = 0;
    setInterval(() => {
        slides[current].classList.remove('active');
        current = (current + 1) % slides.length;
        slides[current].classList.add('active');
    }, 6000); 
}

class AutoCarousel {
    constructor(track) {
        this.track = track;
        this.cards = Array.from(track.children);
        if (this.cards.length === 0) return;
        this.settings = { interval: 3000, transitionTime: 600, gap: 24 };
        this.index = 0;
        this.cardWidth = this.cards[0].offsetWidth + this.settings.gap;
        this.init();
    }
    init() {
        this.cards.forEach(card => this.track.appendChild(card.cloneNode(true)));
        this.start();
    }
    start() { this.timer = setInterval(() => this.move(), this.settings.interval); }
    move() {
        this.index++;
        this.track.style.transition = `transform ${this.settings.transitionTime}ms ease`;
        this.track.style.transform = `translateX(${-this.index * this.cardWidth}px)`;
        if (this.index >= this.cards.length) {
            setTimeout(() => {
                this.track.style.transition = 'none';
                this.index = 0;
                this.track.style.transform = `translateX(0)`;
            }, this.settings.transitionTime);
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    initHeroSlider();

    const isMobile = window.innerWidth <= 768;
    
    setTimeout(() => {
        // Radius settings for perfect balance
        const innerRadius = 185; 
        const outerRadius = 315; 

        // Draw circles and radiating spokes
        arrangeCircle('categories', innerRadius, true); 
        
        if (!isMobile) {
            arrangeCircle('suppliers', outerRadius, true);            
        } else {
            const supps = document.getElementById('suppliers');
            if(supps) supps.style.display = 'none';
        }
    }, 200);

    document.querySelectorAll('.cards-container').forEach(track => {
        new AutoCarousel(track);
    });


    /**
     * Mahitaji Global UI Components
     * Unified Password Visibility Toggle (Sentence Case)
     */
    document.addEventListener('click', function (e) {
        const button = e.target.closest('.toggle-password');
        
        if (button) {
            e.preventDefault();
            
            const targetId = button.getAttribute('data-target');
            const input = document.getElementById(targetId);
            
            if (input) {
                if (input.type === 'password') {
                    input.type = 'text';
                    button.innerText = 'Hide'; // Unified to sentence case
                } else {
                    input.type = 'password';
                    button.innerText = 'Show'; // Unified to sentence case
                }
            }
        }
    });


    

});


const body = document.body;
const hero = document.querySelector('.hero');

// If NOT homepage → always solid dropdown
if (!hero) {
    body.classList.add('dropdown-solid');
} else {
    // Homepage → switch on scroll
    function handleDropdown() {
        const trigger = hero.offsetHeight - 80;

        if (window.scrollY > trigger) {
            body.classList.add('dropdown-solid');
        } else {
            body.classList.remove('dropdown-solid');
        }
    }

    handleDropdown();
    window.addEventListener('scroll', handleDropdown);
}

