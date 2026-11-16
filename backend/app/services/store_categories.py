import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import ProductCategory


STORE_CATEGORIES = (
    {
        "slug": "medicines",
        "name": "Medicines",
        "description": "Medicines and pharmacist-reviewed essentials.",
        "image_url": "/assets/categories/medicines.jpg",
        "aliases": ("medicine", "medications", "pharmacy products"),
    },
    {
        "slug": "creams-gels",
        "name": "Creams & Gels",
        "description": "Topical creams, gels and ointments.",
        "image_url": "/assets/categories/creams-gels.jpg",
        "aliases": ("cream", "creams", "gel", "gels", "creams and gels", "topical products", "ointments"),
    },
    {
        "slug": "first-aid-wound-care",
        "name": "First Aid & Wound Care",
        "description": "Bandages and first-aid supplies.",
        "image_url": "/assets/categories/first-aid.jpg",
        "aliases": ("first aid", "wound care", "bandages", "first aid and wound care"),
    },
    {
        "slug": "personal-care",
        "name": "Personal Care",
        "description": "Everyday personal-care essentials.",
        "image_url": "/assets/categories/personal-care.jpg",
        "aliases": ("personal care", "personal hygiene", "toiletries"),
    },
    {
        "slug": "baby-care",
        "name": "Baby Care",
        "description": "Baby-care products and essentials.",
        "image_url": "/assets/categories/baby-care.jpg",
        "aliases": ("baby", "infant care", "baby products"),
    },
    {
        "slug": "health-nutrition",
        "name": "Health & Nutrition",
        "description": "Health and nutrition products.",
        "image_url": "/assets/categories/health-nutrition.jpg",
        "aliases": ("health nutrition", "health and nutrition", "nutrition", "nutritional products"),
    },
    {
        "slug": "vitamins-minerals",
        "name": "Vitamins & Minerals",
        "description": "Vitamins and minerals.",
        "image_url": "/assets/categories/vitamins-minerals.jpg",
        "aliases": ("vitamins", "minerals", "vitamin", "vitamins and minerals", "mineral supplements"),
    },
    {
        "slug": "medical-equipment",
        "name": "Medical Equipment",
        "description": "Thermometers and medical equipment.",
        "image_url": "/assets/categories/medical-equipment.jpg",
        "aliases": ("medical equipment", "medical devices", "equipment"),
    },
    {
        "slug": "hygiene-sanitary-products",
        "name": "Hygiene & Sanitary Products",
        "description": "Hygiene and sanitary essentials.",
        "image_url": "/assets/categories/hygiene-sanitary.jpg",
        "aliases": (
            "hygiene",
            "sanitary products",
            "feminine hygiene",
            "sanitary",
            "hygiene and sanitary products",
            "sanitary and hygiene products",
        ),
    },
)


def category_name_key(value: str) -> str:
    return " ".join(value.casefold().split())


def normalized_category_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def category_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:80] or "category"


def seed_store_categories(db: Session) -> int:
    categories = db.scalars(select(ProductCategory).order_by(ProductCategory.id)).all()
    slug_owner = {category.slug: category for category in categories if category.slug}

    for category in categories:
        category.name_key = category_name_key(category.name)
        if not category.slug:
            candidate = category_slug(category.name)
            if candidate in slug_owner and slug_owner[candidate].id != category.id:
                candidate = f"{candidate}-{category.id}"
            category.slug = candidate
            slug_owner[candidate] = category

    created = 0
    for definition in STORE_CATEGORIES:
        category = slug_owner.get(definition["slug"])
        if category is None:
            category = next(
                (item for item in categories if item.name_key == category_name_key(definition["name"])),
                None,
            )
        if category is None:
            category = ProductCategory(
                name=definition["name"],
                name_key=category_name_key(definition["name"]),
                slug=definition["slug"],
                description=definition["description"],
                image_url=definition["image_url"],
                active=True,
            )
            db.add(category)
            slug_owner[definition["slug"]] = category
            categories.append(category)
            created += 1
            continue

        category.slug = definition["slug"]
        category.name_key = category_name_key(category.name)
        if category.description is None:
            category.description = definition["description"]
        if category.image_url is None:
            category.image_url = definition["image_url"]
        slug_owner[definition["slug"]] = category

    db.flush()
    return created
