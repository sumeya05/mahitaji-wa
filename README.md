# 🛒 Mahitaji E-commerce Platform

A simple, scalable wholesale e-commerce platform built with Django, designed for SMEs to manage and distribute goods efficiently.

---

## 🚀 Overview

Mahitaji is a lightweight e-commerce system tailored for wholesalers and retailers.
It focuses on simplicity, performance, and practical usability for real-world business operations.

This project is part of a larger goal to build reliable digital infrastructure for small and medium-sized businesses.

---

## ✨ Features

* 🏠 Clean homepage with product highlights
* 🛍️ Product catalog (categories & brands)
* 🛒 Shopping cart system (in progress)
* 👤 User dashboard (in progress)
* 🔍 Search functionality
* 📱 Responsive design (mobile-friendly)
* ⚡ Fast and minimal frontend (HTML, CSS, JS only)

---

## 🧱 Tech Stack

* **Backend:** Django (Python)
* **Frontend:** HTML, CSS, JavaScript (vanilla)
* **Database:** MySQL (planned / in use)
* **Environment:** Virtualenv / Conda

---

## 📂 Project Structure

```
project_root/
│
├── core/                  # Main app (views, urls, templates)
├── templates/
│   ├── base/
│   │   └── base.html
│   └── core/
│       ├── home.html
│       └── ...
│
├── static/
│   ├── main.css
│   ├── main.js
│   ├── assets/
│   └── media/
│
├── manage.py
└── requirements.txt
```

---

## ⚙️ Installation & Setup

### 1. Clone the repository

```
git clone https://github.com/isuba-ian-k/mahitaji-wa.git
cd mahitaji-wa
```

### 2. Create virtual environment

```
python -m venv venv
source venv/bin/activate   # Linux / Mac
venv\Scripts\activate      # Windows
```

### 3. Install dependencies

```
pip install -r requirements.txt
```

### 4. Run migrations

```
python manage.py migrate
```

### 5. Start development server

```
python manage.py runserver
```

---

## 🔧 Configuration

Make sure in `settings.py`:

```
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
```

---

## 📌 Current Status

* Frontend structure complete ✅
* Django template integration complete ✅
* Backend logic in progress ⚙️
* Dynamic product system (coming next)

---

## 🎯 Goals

* Build a fully functional SME e-commerce system
* Integrate real-time inventory & order tracking
* Support wholesalers and retailers efficiently
* Keep the system simple, fast, and maintainable

---

## 🤝 Contributing

This project is currently under active development.
Contributions, ideas, and feedback are welcome.

---

## 📄 License

This project is open-source and available under the MIT License.

---

## 👨‍💻 Author

Built by **Ian IK**
Passionate about backend systems, scalable solutions, and real-world impact through technology.

---
