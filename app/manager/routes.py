import sqlite3
from functools import wraps
from flask import Blueprint, render_template, session, redirect, url_for, flash, request

from ..db import get_db
from ..models.product import Product
from ..models.brand import Brand
from ..models.category import Category

manager_bp = Blueprint("manager", __name__)


def manager_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "manager":
            return redirect(url_for("auth.login"))
        return fn(*args, **kwargs)
    return wrapper


def _get_manager_shop(db):
    return db.execute("""
        SELECT s.id, s.name, s.created_at
        FROM shops s
        JOIN shop_managers sm ON sm.shop_id = s.id
        WHERE sm.manager_user_id = ?
        LIMIT 1;
    """, (session.get("user_id"),)).fetchone()


@manager_bp.route("/", methods=["GET"])
@manager_required
def dashboard():
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned to this manager account.", "error")
        return redirect(url_for("auth.logout"))

    products = Product.all_by_shop(db, shop["id"])
    brands = Brand.all_by_shop(db, shop["id"])
    categories = Category.all_by_shop(db, shop["id"])
    total_products = len(products)
    total_stock = sum(p["quantity"] for p in products)
    out_of_stock = sum(1 for p in products if p["quantity"] == 0)

    category_products = {c["id"]: [] for c in categories}
    for p in products:
        cid = p["category_id"]
        if cid in category_products:
            category_products[cid].append(p)

    category_counts = {cid: len(items) for cid, items in category_products.items()}

    return render_template(
        "manager.html",
        shop=shop,
        products=products,
        brands=brands,
        categories=categories,
        category_products=category_products,
        category_counts=category_counts,
        total_products=total_products,
        total_stock=total_stock,
        out_of_stock=out_of_stock,
    )


@manager_bp.route("/products/create", methods=["POST"])
@manager_required
def create_product():
    name = request.form.get("product_name", "").strip()
    brand_id_raw = request.form.get("product_brand_id")
    category_id_raw = request.form.get("product_category_id")

    if not name:
        flash("Product name is required.", "error")
        return redirect(url_for("manager.dashboard"))

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    brand_id = None
    if brand_id_raw:
        try:
            brand_id = int(brand_id_raw)
        except ValueError:
            brand_id = None

    if brand_id:
        brand = Brand.get_by_id(db, shop["id"], brand_id)
        if not brand:
            flash("Invalid brand selected.", "error")
            return redirect(url_for("manager.dashboard"))

    category_id = None
    if category_id_raw:
        try:
            category_id = int(category_id_raw)
        except ValueError:
            category_id = None

    if category_id:
        category = Category.get_by_id(db, shop["id"], category_id)
        if not category:
            flash("Invalid category selected.", "error")
            return redirect(url_for("manager.dashboard"))
    else:
        flash("Please select a category.", "error")
        return redirect(url_for("manager.dashboard"))

    try:
        Product.create(db, shop["id"], name, 0.0, brand_id, category_id)
        db.commit()
        flash("Product registered successfully.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("This SKU already exists for your shop.", "error")

    return redirect(url_for("manager.dashboard"))


@manager_bp.route("/products/add_stock", methods=["POST"])
@manager_required
def add_stock():
    product_id = request.form.get("product_id")
    quantity_raw = request.form.get("stock_quantity", "0").strip()
    price_raw = request.form.get("stock_price", "0").strip()

    try:
        quantity = int(quantity_raw)
    except ValueError:
        quantity = -1

    try:
        price = float(price_raw)
        if price < 0:
            raise ValueError
    except ValueError:
        flash("Enter a valid price.", "error")
        return redirect(url_for("manager.dashboard"))

    if not product_id or quantity <= 0:
        flash("Select a product and enter a positive quantity.", "error")
        return redirect(url_for("manager.dashboard"))

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    product = Product.get_for_shop(db, shop["id"], int(product_id))
    if not product:
        flash("Invalid product selected.", "error")
        return redirect(url_for("manager.dashboard"))

    Product.add_stock(db, product["id"], quantity, price)
    db.commit()
    flash(f"Added {quantity} units to {product['name']} at PKR {price:.2f}.", "success")
    return redirect(url_for("manager.dashboard"))


@manager_bp.route("/brands/create", methods=["POST"])
@manager_required
def create_brand():
    name = request.form.get("brand_name", "").strip()
    if not name:
        flash("Brand name is required.", "error")
        return redirect(url_for("manager.dashboard"))

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    try:
        Brand.create(db, shop["id"], name)
        db.commit()
        flash("Brand added.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Brand already exists for this shop.", "error")

    return redirect(url_for("manager.dashboard"))


@manager_bp.route("/brands/update", methods=["POST"])
@manager_required
def update_brand():
    brand_id = request.form.get("brand_id")
    name = request.form.get("brand_new_name", "").strip()

    try:
        brand_id = int(brand_id)
    except (TypeError, ValueError):
        flash("Invalid brand.", "error")
        return redirect(url_for("manager.dashboard"))

    if not name:
        flash("Brand name is required.", "error")
        return redirect(url_for("manager.dashboard"))

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    brand = Brand.get_by_id(db, shop["id"], brand_id)
    if not brand:
        flash("Brand not found.", "error")
        return redirect(url_for("manager.dashboard"))

    try:
        Brand.update(db, shop["id"], brand_id, name)
        db.commit()
        flash("Brand updated.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Another brand already uses that name.", "error")

    return redirect(url_for("manager.dashboard"))


@manager_bp.route("/products/update", methods=["POST"])
@manager_required
def update_product():
    product_id = request.form.get("edit_product_id")
    name = request.form.get("edit_product_name", "").strip()
    brand_id_raw = request.form.get("edit_product_brand_id")
    category_id_raw = request.form.get("edit_product_category_id")

    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        flash("Invalid product.", "error")
        return redirect(url_for("manager.dashboard"))

    if not name:
        flash("Product name is required.", "error")
        return redirect(url_for("manager.dashboard"))

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    brand_id = None
    if brand_id_raw:
        try:
            brand_id = int(brand_id_raw)
        except ValueError:
            brand_id = None
    if brand_id:
        brand = Brand.get_by_id(db, shop["id"], brand_id)
        if not brand:
            flash("Brand not found.", "error")
            return redirect(url_for("manager.dashboard"))

    category_id = None
    if category_id_raw:
        try:
            category_id = int(category_id_raw)
        except ValueError:
            category_id = None
    if category_id:
        category = Category.get_by_id(db, shop["id"], category_id)
        if not category:
            flash("Category not found.", "error")
            return redirect(url_for("manager.dashboard"))

    product = Product.get_for_shop(db, shop["id"], product_id)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("manager.dashboard"))

    current_price = product["price"]

    try:
        Product.update(
            db,
            shop["id"],
            product_id,
            name=name,
            price=current_price,
            brand_id=brand_id if brand_id is not None else product["brand_id"],
            category_id=category_id if category_id is not None else product["category_id"],
        )
        db.commit()
        flash("Product updated.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("SKU already exists.", "error")

    return redirect(url_for("manager.dashboard"))


@manager_bp.route("/products/delete", methods=["POST"])
@manager_required
def delete_product():
    product_id = request.form.get("delete_product_id")

    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        flash("Invalid product.", "error")
        return redirect(url_for("manager.dashboard"))

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    product = Product.get_for_shop(db, shop["id"], product_id)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("manager.dashboard"))

    Product.delete(db, shop["id"], product_id)
    db.commit()
    flash(f"Removed {product['name']}.", "success")
    return redirect(url_for("manager.dashboard"))


@manager_bp.route("/categories/create", methods=["POST"])
@manager_required
def create_category():
    name = request.form.get("category_name", "").strip()
    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for("manager.dashboard"))

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    try:
        Category.create(db, shop["id"], name)
        db.commit()
        flash("Category added.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Category already exists for this shop.", "error")

    return redirect(url_for("manager.dashboard"))


@manager_bp.route("/categories/update", methods=["POST"])
@manager_required
def update_category():
    category_id = request.form.get("category_id")
    name = request.form.get("category_new_name", "").strip()

    try:
        category_id = int(category_id)
    except (TypeError, ValueError):
        flash("Invalid category.", "error")
        return redirect(url_for("manager.dashboard"))

    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for("manager.dashboard"))

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    category = Category.get_by_id(db, shop["id"], category_id)
    if not category:
        flash("Category not found.", "error")
        return redirect(url_for("manager.dashboard"))

    try:
        Category.update(db, shop["id"], category_id, name)
        db.commit()
        flash("Category updated.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Another category already uses that name.", "error")

    return redirect(url_for("manager.dashboard"))
