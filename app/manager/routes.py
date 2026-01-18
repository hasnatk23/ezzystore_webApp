import sqlite3
from functools import wraps
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, session, redirect, url_for, flash, request

from ..db import get_db
from ..models.product import Product
from ..models.brand import Brand
from ..models.category import Category
from ..models.stock_batch import StockBatch
from ..models.sale import Sale
from ..models.customer import Customer

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


def _url_for_page(page: str | None):
    mapping = {
        "overview": "manager.dashboard",
        "products": "manager.products_page",
        "stock": "manager.stock_page",
        "sales": "manager.sales_page",
        "reports": "manager.reports_page",
        "customers": "manager.customers_page",
        "brands": "manager.brands_page",
        "categories": "manager.categories_page",
    }
    if page in mapping:
        return url_for(mapping[page])
    return url_for("manager.dashboard")


def _redirect_to_page(page: str | None = None):
    return redirect(_url_for_page(page))


def _build_manager_context(db, shop, active_page: str):
    products = Product.all_by_shop(db, shop["id"])
    brands = Brand.all_by_shop(db, shop["id"])
    categories = Category.all_by_shop(db, shop["id"])
    total_products = len(products)
    total_stock = sum(p["quantity"] for p in products)
    out_of_stock = sum(1 for p in products if p["quantity"] <= (p["reorder_level"] or 0))

    category_products = {c["id"]: [] for c in categories}
    brand_products = {b["id"]: [] for b in brands}
    for p in products:
        cid = p["category_id"]
        if cid in category_products:
            category_products[cid].append(p)
        bid = p["brand_id"]
        if bid in brand_products:
            brand_products[bid].append(p)

    category_counts = {cid: len(items) for cid, items in category_products.items()}
    brand_counts = {bid: len(items) for bid, items in brand_products.items()}
    stock_batches = StockBatch.all_by_shop(db, shop["id"])
    product_latest = {}
    product_purchase_summary = {}
    product_purchase_previews = {}
    product_sale_defaults = {}
    stock_batch_summary_map = {}
    for batch in stock_batches:
        pid = batch["product_id"]
        if pid not in product_latest:
            product_latest[pid] = {
                "purchase_rate": batch["purchase_rate"],
                "sale_price": batch["sale_price"],
            }
        summary = stock_batch_summary_map.setdefault(
            batch["batch_date"],
            {
                "batch_date": batch["batch_date"],
                "product_count": 0,
                "total_purchase": 0.0,
            },
        )
        summary["product_count"] += 1
        summary["total_purchase"] += (batch["purchase_rate"] * batch["quantity"])
        purchase_summary = product_purchase_summary.setdefault(
            pid,
            {
                "total_batches": 0,
                "total_quantity": 0,
                "total_spend": 0.0,
            },
        )
        purchase_summary["total_batches"] += 1
        purchase_summary["total_quantity"] += batch["quantity"]
        purchase_summary["total_spend"] += batch["quantity"] * batch["purchase_rate"]
        previews = product_purchase_previews.setdefault(pid, [])
        if len(previews) < 3:
            previews.append(
                {
                    "batch_date": batch["batch_date"],
                    "quantity": batch["quantity"],
                    "purchase_rate": batch["purchase_rate"],
                }
            )
    for batch in reversed(stock_batches):
        pid = batch["product_id"]
        if pid not in product_sale_defaults:
            product_sale_defaults[pid] = batch["sale_price"]
    stock_batch_summary = sorted(
        stock_batch_summary_map.values(),
        key=lambda item: item["batch_date"],
        reverse=True,
    )
    today = date.today()
    today_iso = today.isoformat()

    report_start_iso = today_iso
    report_end_iso = today_iso
    report_sales = []
    report_daily_summary = []
    report_search_performed = False

    def _parse_report_date(raw_value, default_value):
        if not raw_value:
            return default_value
        try:
            return datetime.strptime(raw_value, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return default_value

    if active_page == "reports":
        # Check if user has actually provided date parameters.
        start_param = request.args.get("sales_report_start")
        end_param = request.args.get("sales_report_end")
        report_search_performed = bool(start_param or end_param)

        if report_search_performed:
            report_start_date = _parse_report_date(start_param, today)
            report_end_date = _parse_report_date(end_param, report_start_date)
        else:
            # Default to the last 7 days so reports are never empty on load.
            report_end_date = today
            report_start_date = today - timedelta(days=6)
            report_search_performed = True

        if report_end_date < report_start_date:
            report_end_date = report_start_date

        report_start_iso = report_start_date.isoformat()
        report_end_iso = report_end_date.isoformat()
        report_sales = Sale.by_date_with_items(db, shop["id"], report_start_iso, report_end_iso)
        report_daily_summary = Sale.daily_summary(db, shop["id"], report_start_iso, report_end_iso)

    recent_sales = Sale.recent_with_items(db, shop["id"], limit=5)
    customers = Customer.all_by_shop(db, shop["id"])
    customers_serialized = [dict(customer) for customer in customers]

    customer_insights = []
    for customer in customers:
        sale_rows = db.execute("""
            SELECT s.created_at, si.product_id, si.quantity, si.unit_price
            FROM sales s
            JOIN sale_items si ON si.sale_id = s.id
            WHERE s.shop_id = ?
              AND s.customer_id = ?
              AND s.sale_type = 'sale';
        """, (shop["id"], customer["id"])).fetchall()

        total_items = 0
        sale_total = 0.0
        purchase_total = 0.0
        last_purchase = None

        for row in sale_rows:
            qty = row["quantity"] or 0
            price = row["unit_price"] or 0.0
            total_items += qty
            sale_total += qty * price
            latest_rates = product_latest.get(row["product_id"]) or {}
            purchase_total += qty * (latest_rates.get("purchase_rate") or 0.0)
            created_at = row["created_at"]
            if created_at and (last_purchase is None or created_at > last_purchase):
                last_purchase = created_at

        profit_pct = None
        if purchase_total > 0:
            profit_pct = ((sale_total - purchase_total) / purchase_total) * 100

        if total_items > 0:
            customer_insights.append(
                {
                    "id": customer["id"],
                    "name": customer["name"],
                    "phone": customer["phone"],
                    "item_count": total_items,
                    "sale_total": sale_total,
                    "purchase_total": purchase_total,
                    "last_purchase": last_purchase,
                    "profit_pct": profit_pct,
                }
            )

    return {
        "shop": shop,
        "products": products,
        "brands": brands,
        "categories": categories,
        "category_products": category_products,
        "category_counts": category_counts,
        "brand_counts": brand_counts,
        "stock_batches": stock_batches,
        "stock_batch_summary": stock_batch_summary,
        "product_latest": product_latest,
        "product_purchase_summary": product_purchase_summary,
        "product_purchase_previews": product_purchase_previews,
        "product_sale_defaults": product_sale_defaults,
        "recent_sales": recent_sales,
        "report_sales": report_sales,
        "report_daily_summary": report_daily_summary,
        "report_start": report_start_iso,
        "report_end": report_end_iso,
        "report_search_performed": report_search_performed,
        "customers": customers_serialized,
        "customer_insights": customer_insights,
        "today_iso": today_iso,
        "total_products": total_products,
        "total_stock": total_stock,
        "out_of_stock": out_of_stock,
        "active_page": active_page,
    }


@manager_bp.route("/", methods=["GET"])
@manager_required
def dashboard():
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned to this manager account.", "error")
        return redirect(url_for("auth.logout"))

    page_param = request.args.get("page")
    report_params = request.args.get("sales_report_start") or request.args.get("sales_report_end")
    active_page = page_param or ("reports" if report_params else "products")
    show_module_cards = False
    ctx = _build_manager_context(db, shop, active_page)
    ctx["show_module_cards"] = show_module_cards
    return render_template("manager.html", **ctx)


@manager_bp.route("/products", methods=["GET"])
@manager_required
def products_page():
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned to this manager account.", "error")
        return redirect(url_for("auth.logout"))
    ctx = _build_manager_context(db, shop, "products")
    return render_template("manager.html", **ctx)


@manager_bp.route("/stock", methods=["GET"])
@manager_required
def stock_page():
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned to this manager account.", "error")
        return redirect(url_for("auth.logout"))
    ctx = _build_manager_context(db, shop, "stock")
    return render_template("manager.html", **ctx)


@manager_bp.route("/sales", methods=["GET"])
@manager_required
def sales_page():
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned to this manager account.", "error")
        return redirect(url_for("auth.logout"))
    selected_customer_id = None
    customer_id_raw = request.args.get("customer_id")
    if customer_id_raw:
        try:
            customer_id = int(customer_id_raw)
        except (TypeError, ValueError):
            flash("Invalid customer selection.", "error")
        else:
            customer = Customer.get_for_shop(db, shop["id"], customer_id)
            if customer:
                selected_customer_id = customer_id
            else:
                flash("Selected customer not found.", "error")
    ctx = _build_manager_context(db, shop, "sales")
    ctx["selected_customer_id"] = selected_customer_id
    return render_template("manager.html", **ctx)


@manager_bp.route("/reports", methods=["GET"])
@manager_required
def reports_page():
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned to this manager account.", "error")
        return redirect(url_for("auth.logout"))
    ctx = _build_manager_context(db, shop, "reports")
    return render_template("manager.html", **ctx)


@manager_bp.route("/customers", methods=["GET"])
@manager_required
def customers_page():
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned to this manager account.", "error")
        return redirect(url_for("auth.logout"))
    ctx = _build_manager_context(db, shop, "customers")
    return render_template("manager.html", **ctx)


@manager_bp.route("/brands", methods=["GET"])
@manager_required
def brands_page():
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned to this manager account.", "error")
        return redirect(url_for("auth.logout"))
    ctx = _build_manager_context(db, shop, "brands")
    return render_template("manager.html", **ctx)


@manager_bp.route("/categories", methods=["GET"])
@manager_required
def categories_page():
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned to this manager account.", "error")
        return redirect(url_for("auth.logout"))
    ctx = _build_manager_context(db, shop, "categories")
    return render_template("manager.html", **ctx)


@manager_bp.route("/products/create", methods=["POST"])
@manager_required
def create_product():
    name = request.form.get("product_name", "").strip()
    brand_id_raw = request.form.get("product_brand_id")
    category_id_raw = request.form.get("product_category_id")
    reorder_level_raw = request.form.get("product_reorder_level", "3")

    if not name:
        flash("Product name is required.", "error")
        return _redirect_to_page("products")

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
            return _redirect_to_page("products")

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
            return _redirect_to_page("products")
    else:
        flash("Please select a category.", "error")
        return _redirect_to_page("products")

    try:
        reorder_level = int(reorder_level_raw)
        if reorder_level < 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Enter a valid minimum stock level (0 or above).", "error")
        return _redirect_to_page("products")

    try:
        Product.create(db, shop["id"], name, 0.0, brand_id, category_id, reorder_level)
        db.commit()
        flash("Product registered successfully.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("This SKU already exists for your shop.", "error")

    return _redirect_to_page("products")


@manager_bp.route("/products/add_stock", methods=["POST"])
@manager_required
def add_stock():
    def parse_float(value_raw, label):
        try:
            value = float(value_raw)
            if value < 0:
                raise ValueError
            return value
        except ValueError:
            flash(f"Enter a valid {label}.", "error")
            return None

    entries = []
    multi_ids = request.form.getlist("batch_product_id[]")
    batch_date_group = request.form.get("batch_date_group", "").strip()

    if multi_ids:
        quantities = request.form.getlist("batch_quantity[]")
        purchase_rates = request.form.getlist("batch_purchase_rate[]")
        sale_prices = request.form.getlist("batch_sale_price[]")
        total = len(multi_ids)
        if not (len(quantities) == len(purchase_rates) == len(sale_prices) == total):
            flash("Missing restock fields for one of the products.", "error")
            return _redirect_to_page("stock")
        if batch_date_group:
            try:
                batch_date_common = datetime.strptime(batch_date_group, "%Y-%m-%d").date().isoformat()
            except ValueError:
                flash("Enter a valid restock date.", "error")
                return _redirect_to_page("stock")
        else:
            batch_date_common = date.today().isoformat()
        for idx in range(total):
            try:
                pid = int(multi_ids[idx])
            except (TypeError, ValueError):
                flash("Invalid product selected.", "error")
                return _redirect_to_page("stock")
            try:
                quantity = int(quantities[idx])
            except (TypeError, ValueError):
                flash("Enter a valid quantity.", "error")
                return _redirect_to_page("stock")
            purchase_rate = parse_float(purchase_rates[idx], "purchase rate")
            if purchase_rate is None:
                return _redirect_to_page("stock")
            sale_price = parse_float(sale_prices[idx], "sale price")
            if sale_price is None:
                return _redirect_to_page("stock")
            entries.append(
                {
                    "product_id": pid,
                    "quantity": quantity,
                    "purchase_rate": purchase_rate,
                    "sale_price": sale_price,
                    "batch_date": batch_date_common,
                }
            )
    else:
        product_id = request.form.get("product_id")
        quantity_raw = request.form.get("stock_quantity", "0").strip()
        purchase_rate_raw = request.form.get("purchase_rate", "0").strip()
        sale_price_raw = request.form.get("stock_sale_price", "0").strip()
        batch_date_raw = request.form.get("batch_date", "").strip()

        try:
            quantity = int(quantity_raw)
        except ValueError:
            quantity = -1

        purchase_rate = parse_float(purchase_rate_raw, "purchase rate")
        if purchase_rate is None:
            return _redirect_to_page("stock")
        sale_price = parse_float(sale_price_raw, "sale price")
        if sale_price is None:
            return _redirect_to_page("stock")

        if batch_date_raw:
            try:
                batch_date = datetime.strptime(batch_date_raw, "%Y-%m-%d").date().isoformat()
            except ValueError:
                flash("Enter a valid restock date.", "error")
                return _redirect_to_page("stock")
        else:
            batch_date = date.today().isoformat()

        if not product_id or quantity <= 0:
            flash("Select a product and enter a positive quantity.", "error")
            return _redirect_to_page("stock")

        entries.append(
            {
                "product_id": int(product_id),
                "quantity": quantity,
                "purchase_rate": purchase_rate,
                "sale_price": sale_price,
                "batch_date": batch_date,
            }
        )

    if not entries:
        flash("No restock data provided.", "error")
        return _redirect_to_page("stock")

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    processed = []
    for entry in entries:
        if entry["quantity"] <= 0:
            flash("Quantity must be greater than zero.", "error")
            return _redirect_to_page("stock")
        product = Product.get_for_shop(db, shop["id"], entry["product_id"])
        if not product:
            flash("Invalid product selected.", "error")
            return _redirect_to_page("stock")
        Product.add_stock(db, product["id"], entry["quantity"], entry["sale_price"])
        StockBatch.create(
            db,
            shop["id"],
            product["id"],
            entry["quantity"],
            entry["purchase_rate"],
            entry["sale_price"],
            entry["batch_date"],
        )
        processed.append(product["name"])

    db.commit()
    if len(processed) == 1:
        flash(
            f"Restock recorded for {processed[0]} ({entries[0]['quantity']} units at PKR {entries[0]['purchase_rate']:.2f}).",
            "success",
        )
    else:
        flash(f"Restock recorded for {len(processed)} products.", "success")
    return _redirect_to_page("stock")


@manager_bp.route("/sales/record", methods=["POST"])
@manager_required
def record_sale():
    def parse_float(value_raw, label):
        try:
            value = float(value_raw)
            if value < 0:
                raise ValueError
            return value
        except ValueError:
            flash(f"Enter a valid {label}.", "error")
            return None

    sale_type = request.form.get("sale_type", "sale")
    if sale_type not in ("sale", "return"):
        sale_type = "sale"

    product_ids = request.form.getlist("sale_product_id[]")
    quantities = request.form.getlist("sale_quantity[]")
    prices = request.form.getlist("sale_price[]")
    customer_id_raw = request.form.get("sale_customer_id")

    if not product_ids:
        flash("Select at least one product to record a sale or return.", "error")
        return _redirect_to_page("sales")
    if not (len(product_ids) == len(quantities) == len(prices)):
        flash("Missing sale fields for one of the products.", "error")
        return _redirect_to_page("sales")

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    entries = []
    customer_id = None
    if customer_id_raw:
        try:
            customer_id = int(customer_id_raw)
        except (TypeError, ValueError):
            customer_id = None
    for idx in range(len(product_ids)):
        try:
            pid = int(product_ids[idx])
        except (TypeError, ValueError):
            flash("Invalid product selected.", "error")
            return _redirect_to_page("sales")
        try:
            quantity = int(quantities[idx])
        except (TypeError, ValueError):
            flash("Enter a valid quantity.", "error")
            return _redirect_to_page("sales")
        if quantity <= 0:
            flash("Quantity must be greater than zero.", "error")
            return _redirect_to_page("sales")
        price = parse_float(prices[idx], "sale price")
        if price is None:
            return _redirect_to_page("sales")

        product = Product.get_for_shop(db, shop["id"], pid)
        if not product:
            flash("Product not found.", "error")
            return _redirect_to_page("sales")
        if sale_type == "sale" and product["quantity"] < quantity:
            flash(f"Not enough stock for {product['name']}.", "error")
            return _redirect_to_page("sales")

        entries.append(
            {
                "product_id": pid,
                "quantity": quantity,
                "unit_price": price,
                "product_name": product["name"],
            }
        )

    if customer_id:
        customer = Customer.get_for_shop(db, shop["id"], customer_id)
        if not customer:
            flash("Selected customer not found.", "error")
            return _redirect_to_page("sales")

    try:
        for entry in entries:
            delta = -entry["quantity"] if sale_type == "sale" else entry["quantity"]
            Product.adjust_quantity(db, shop["id"], entry["product_id"], delta)
        Sale.record(
            db,
            shop["id"],
            sale_type,
            [{"product_id": e["product_id"], "quantity": e["quantity"], "unit_price": e["unit_price"]} for e in entries],
            customer_id=customer_id,
        )
        db.commit()
        if sale_type == "sale":
            flash(f"Recorded sale for {len(entries)} product(s).", "success")
        else:
            flash(f"Recorded return for {len(entries)} product(s).", "success")
    except Exception:
        db.rollback()
        flash("Failed to record sale/return.", "error")

    return _redirect_to_page("sales")


@manager_bp.route("/sales/<int:sale_id>/return", methods=["POST"])
@manager_required
def sale_return(sale_id: int):
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    try:
        sale_id = int(sale_id)
    except (TypeError, ValueError):
        flash("Invalid sale reference.", "error")
        return _redirect_to_page("sales")

    sale, sale_items = Sale.get_with_items(db, shop["id"], sale_id)
    if not sale:
        flash("Sale not found.", "error")
        return _redirect_to_page("sales")
    if sale["sale_type"] != "sale":
        flash("Only sales can be returned.", "error")
        return _redirect_to_page("sales")

    posted_ids = request.form.getlist("return_sale_item_id[]")
    posted_qty = request.form.getlist("return_quantity[]")
    posted_prices = request.form.getlist("return_price[]")
    if not posted_ids or not (len(posted_ids) == len(posted_qty) == len(posted_prices)):
        flash("Return form incomplete.", "error")
        return _redirect_to_page("sales")

    sale_item_lookup = {str(item["id"]): item for item in sale_items}
    entries = []
    for idx in range(len(posted_ids)):
        item_id = posted_ids[idx]
        sale_item = sale_item_lookup.get(item_id)
        if not sale_item:
            flash("Invalid sale item selected.", "error")
            return _redirect_to_page("sales")
        available_to_return = sale_item["quantity"] - (sale_item.get("returned_quantity") or 0)
        if available_to_return <= 0:
            flash("This product has already been fully returned.", "error")
            return _redirect_to_page("sales")
        try:
            qty = int(posted_qty[idx])
        except (TypeError, ValueError):
            flash("Enter a valid quantity.", "error")
            return _redirect_to_page("sales")
        if qty <= 0 or qty > available_to_return:
            flash("Return quantity must be between 1 and the sold amount.", "error")
            return _redirect_to_page("sales")
        try:
            price = float(posted_prices[idx])
            if price < 0:
                raise ValueError
        except (TypeError, ValueError):
            flash("Enter a valid price.", "error")
            return _redirect_to_page("sales")
        entries.append(
            {
                "product_id": sale_item["product_id"],
                "quantity": qty,
                "unit_price": price,
                "product_name": sale_item["product_name"],
                "sale_item_id": sale_item["id"],
            }
        )

    if not entries:
        flash("Nothing selected to return.", "error")
        return _redirect_to_page("sales")

    try:
        processed_items = []
        for entry in entries:
            Product.adjust_quantity(db, shop["id"], entry["product_id"], entry["quantity"])
            processed_items.append(
                {
                    "product_id": entry["product_id"],
                    "quantity": entry["quantity"],
                    "unit_price": entry["unit_price"],
                }
            )
        Sale.record(
            db,
            shop["id"],
            "return",
            processed_items,
            customer_id=sale["customer_id"],
            reference_sale_id=sale["id"],
        )
        for entry in entries:
            sale_item = sale_item_lookup.get(str(entry["sale_item_id"]))
            current_returned = sale_item.get("returned_quantity") or 0
            total_returned = current_returned + entry["quantity"]
            if total_returned >= sale_item["quantity"]:
                db.execute(
                    "UPDATE sale_items SET returned_quantity = ?, returned_at = datetime('now') WHERE id = ?",
                    (sale_item["quantity"], entry["sale_item_id"]),
                )
            else:
                db.execute(
                    "UPDATE sale_items SET returned_quantity = ?, returned_at = NULL WHERE id = ?",
                    (total_returned, entry["sale_item_id"]),
                )
        db.commit()
        flash(f"Recorded return for {len(entries)} product(s).", "success")
    except Exception:
        db.rollback()
        flash("Failed to record return.", "error")

    return _redirect_to_page("sales")


@manager_bp.route("/brands/create", methods=["POST"])
@manager_required
def create_brand():
    name = request.form.get("brand_name", "").strip()
    if not name:
        flash("Brand name is required.", "error")
        return _redirect_to_page("brands")

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

    return _redirect_to_page("brands")


@manager_bp.route("/brands/update", methods=["POST"])
@manager_required
def update_brand():
    brand_id = request.form.get("brand_id")
    name = request.form.get("brand_new_name", "").strip()

    try:
        brand_id = int(brand_id)
    except (TypeError, ValueError):
        flash("Invalid brand.", "error")
        return _redirect_to_page("brands")

    if not name:
        flash("Brand name is required.", "error")
        return _redirect_to_page("brands")

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    brand = Brand.get_by_id(db, shop["id"], brand_id)
    if not brand:
        flash("Brand not found.", "error")
        return _redirect_to_page("brands")

    try:
        Brand.update(db, shop["id"], brand_id, name)
        db.commit()
        flash("Brand updated.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Another brand already uses that name.", "error")

    return _redirect_to_page("brands")


@manager_bp.route("/products/update", methods=["POST"])
@manager_required
def update_product():
    product_id = request.form.get("edit_product_id")
    name = request.form.get("edit_product_name", "").strip()
    brand_id_raw = request.form.get("edit_product_brand_id")
    category_id_raw = request.form.get("edit_product_category_id")
    reorder_level_raw = request.form.get("edit_product_reorder_level", "3")

    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        flash("Invalid product.", "error")
        return _redirect_to_page("products")

    if not name:
        flash("Product name is required.", "error")
        return _redirect_to_page("products")

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
            return _redirect_to_page("products")

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
            return _redirect_to_page("products")

    product = Product.get_for_shop(db, shop["id"], product_id)
    if not product:
        flash("Product not found.", "error")
        return _redirect_to_page("products")

    try:
        reorder_level = int(reorder_level_raw)
        if reorder_level < 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Enter a valid minimum stock level (0 or above).", "error")
        return _redirect_to_page("products")

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
            reorder_level=reorder_level,
        )
        db.commit()
        flash("Product updated.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("SKU already exists.", "error")

    return _redirect_to_page("products")


@manager_bp.route("/products/delete", methods=["POST"])
@manager_required
def delete_product():
    product_id = request.form.get("delete_product_id")

    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        flash("Invalid product.", "error")
        return _redirect_to_page("products")

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    product = Product.get_for_shop(db, shop["id"], product_id)
    if not product:
        flash("Product not found.", "error")
        return _redirect_to_page("products")

    Product.delete(db, shop["id"], product_id)
    db.commit()
    flash(f"Removed {product['name']}.", "success")
    return _redirect_to_page("products")


@manager_bp.route("/brands/<int:brand_id>", methods=["GET"])
@manager_required
def brand_detail(brand_id: int):
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    try:
        brand_id = int(brand_id)
    except (TypeError, ValueError):
        flash("Invalid brand.", "error")
        return _redirect_to_page("brands")

    brand = Brand.get_by_id(db, shop["id"], brand_id)
    if not brand:
        flash("Brand not found.", "error")
        return _redirect_to_page("brands")

    products = Product.all_by_shop(db, shop["id"])
    brand_products = [p for p in products if p["brand_id"] == brand_id]
    categories = Category.all_by_shop(db, shop["id"])
    brands = Brand.all_by_shop(db, shop["id"])

    return render_template(
        "brand_detail.html",
        shop=shop,
        brand=brand,
        products=brand_products,
        categories=categories,
        brands=brands,
    )


@manager_bp.route("/stock_batches/<batch_date>", methods=["GET"])
@manager_required
def stock_batch_detail(batch_date: str):
    try:
        parsed_date = datetime.strptime(batch_date, "%Y-%m-%d").date().isoformat()
    except ValueError:
        flash("Invalid restock date.", "error")
        return _redirect_to_page("stock")

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    entries = StockBatch.by_date(db, shop["id"], parsed_date)
    if not entries:
        flash("No restock records found for that date.", "error")
        return _redirect_to_page("stock")

    total_purchase = sum(e["purchase_rate"] * e["quantity"] for e in entries)
    total_sale = sum(e["sale_price"] * e["quantity"] for e in entries)

    return render_template(
        "stock_batch_detail.html",
        shop=shop,
        batch_date=parsed_date,
        entries=entries,
        total_purchase=total_purchase,
        total_sale=total_sale,
    )


@manager_bp.route("/products/<int:product_id>/purchases", methods=["GET"])
@manager_required
def product_purchases(product_id: int):
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        flash("Invalid product.", "error")
        return _redirect_to_page("products")

    product = Product.get_for_shop(db, shop["id"], product_id)
    if not product:
        flash("Product not found.", "error")
        return _redirect_to_page("products")

    entries = StockBatch.by_product(db, shop["id"], product_id)
    total_quantity = sum(entry["quantity"] for entry in entries)
    total_spend = sum(entry["quantity"] * entry["purchase_rate"] for entry in entries)

    return render_template(
        "product_purchases.html",
        shop=shop,
        product=product,
        entries=entries,
        total_quantity=total_quantity,
        total_spend=total_spend,
    )


@manager_bp.route("/categories/<int:category_id>", methods=["GET"])
@manager_required
def category_detail(category_id: int):
    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    try:
        category_id = int(category_id)
    except (TypeError, ValueError):
        flash("Invalid category.", "error")
        return _redirect_to_page("categories")

    category = Category.get_by_id(db, shop["id"], category_id)
    if not category:
        flash("Category not found.", "error")
        return _redirect_to_page("categories")

    products = Product.all_by_shop(db, shop["id"])
    category_products = [p for p in products if p["category_id"] == category_id]
    brands = Brand.all_by_shop(db, shop["id"])
    categories = Category.all_by_shop(db, shop["id"])

    return render_template(
        "category_detail.html",
        shop=shop,
        category=category,
        products=category_products,
        brands=brands,
        categories=categories,
    )


@manager_bp.route("/categories/create", methods=["POST"])
@manager_required
def create_category():
    name = request.form.get("category_name", "").strip()
    if not name:
        flash("Category name is required.", "error")
        return _redirect_to_page("categories")

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

    return _redirect_to_page("categories")


@manager_bp.route("/categories/update", methods=["POST"])
@manager_required
def update_category():
    category_id = request.form.get("category_id")
    name = request.form.get("category_new_name", "").strip()

    try:
        category_id = int(category_id)
    except (TypeError, ValueError):
        flash("Invalid category.", "error")
        return _redirect_to_page("categories")

    if not name:
        flash("Category name is required.", "error")
        return _redirect_to_page("categories")

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    category = Category.get_by_id(db, shop["id"], category_id)
    if not category:
        flash("Category not found.", "error")
        return _redirect_to_page("categories")

    try:
        Category.update(db, shop["id"], category_id, name)
        db.commit()
        flash("Category updated.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Another category already uses that name.", "error")

    return _redirect_to_page("categories")


@manager_bp.route("/sales/reports/<report_date>", methods=["GET"])
@manager_required
def sales_report_detail(report_date: str):
    try:
        parsed_date = datetime.strptime(report_date, "%Y-%m-%d").date().isoformat()
    except ValueError:
        flash("Invalid report date.", "error")
        return _redirect_to_page("reports")

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    report_sales = Sale.by_date_with_items(db, shop["id"], parsed_date, parsed_date)
    summary = Sale.daily_summary(db, shop["id"], parsed_date, parsed_date)
    summary_entry = summary[0] if summary else {
        "sale_date": parsed_date,
        "sales_total": 0.0,
        "returns_total": 0.0,
        "sale_count": 0,
        "return_count": 0,
        "sold_items": 0,
        "returned_items": 0,
    }

    return render_template(
        "sales_report_detail.html",
        shop=shop,
        report_date=parsed_date,
        summary=summary_entry,
        report_sales=report_sales,
    )


@manager_bp.route("/customers/create", methods=["POST"])
@manager_required
def create_customer():
    name = request.form.get("customer_name", "").strip()
    phone = request.form.get("customer_phone", "").strip()
    return_to = request.form.get("return_to", "").strip().lower()
    if return_to not in ("sales", "customers"):
        return_to = "customers"

    def _redirect_after(customer_id: int | None = None):
        if return_to == "sales":
            if customer_id:
                return redirect(url_for("manager.sales_page", customer_id=customer_id))
            return redirect(url_for("manager.sales_page"))
        return _redirect_to_page("customers")

    if not name:
        flash("Customer name is required.", "error")
        return _redirect_after()

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    created_customer_id = None
    try:
        created_customer_id = Customer.create(db, shop["id"], name, phone if phone else None)
        db.commit()
        flash("Customer added.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Customer already exists.", "error")
        existing = Customer.get_by_name(db, shop["id"], name)
        if return_to == "sales" and existing:
            return redirect(url_for("manager.sales_page", customer_id=existing["id"]))

    return _redirect_after(created_customer_id)


@manager_bp.route("/customers/delete", methods=["POST"])
@manager_required
def delete_customer():
    customer_id = request.form.get("customer_id")

    try:
        customer_id = int(customer_id)
    except (TypeError, ValueError):
        flash("Invalid customer.", "error")
        return _redirect_to_page("customers")

    db = get_db()
    shop = _get_manager_shop(db)
    if not shop:
        flash("No shop assigned.", "error")
        return redirect(url_for("auth.logout"))

    customer = Customer.get_for_shop(db, shop["id"], customer_id)
    if not customer:
        flash("Customer not found.", "error")
        return _redirect_to_page("customers")

    Customer.delete(db, shop["id"], customer_id)
    db.commit()
    flash(f"Removed customer {customer['name']}.", "success")
    return _redirect_to_page("customers")
