from .models import Category, Brand
from .cart import Cart


def category_renderer(request):
    return {
        'categories': Category.objects.all(),
        'brands': Brand.objects.all(), # This makes brands available in every template
    }

def cart(request):
    return {'cart': Cart(request)}