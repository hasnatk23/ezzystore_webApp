from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from .db import get_db
from .models.user import User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/", methods=["GET"])
def home():
    if session.get("role") == "admin":
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = User.authenticate(db, username, password)

        if user:
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["username"] = user["username"]

            if user["role"] == "admin":
                return redirect(url_for("admin.dashboard"))
            else:
                # manager panel not built yet
                return "Logged in as manager. Manager panel will be added later.", 200

        flash("Invalid username or password", "error")
        return redirect(url_for("auth.login"))

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
