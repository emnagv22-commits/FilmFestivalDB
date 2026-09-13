import os
import hmac
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    flash,
    url_for
)

import mysql.connector
from dotenv import load_dotenv


load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "local-development-secret-key"
)


def get_connection():
    return mysql.connector.connect(
        host=os.getenv(
            "MYSQLHOST",
            os.getenv("DB_HOST", "localhost")
        ),
        port=int(
            os.getenv(
                "MYSQLPORT",
                os.getenv("DB_PORT", "3306")
            )
        ),
        user=os.getenv(
            "MYSQLUSER",
            os.getenv("DB_USER", "root")
        ),
        password=os.getenv(
            "MYSQLPASSWORD",
            os.getenv("DB_PASSWORD", "")
        ),
        database=os.getenv(
            "MYSQLDATABASE",
            os.getenv("DB_NAME", "film_festivals")
        )
    )


def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            flash(
                "Для этого действия необходимо войти как администратор.",
                "error"
            )
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return wrapper


def get_or_create_director(cursor, director_name):
    director_name = director_name.strip()

    cursor.execute(
        """
        SELECT id
        FROM directors
        WHERE LOWER(full_name) = LOWER(%s)
        LIMIT 1
        """,
        (director_name,)
    )

    director = cursor.fetchone()

    if director:
        if isinstance(director, dict):
            return director["id"]

        return director[0]

    cursor.execute(
        """
        INSERT INTO directors (full_name)
        VALUES (%s)
        """,
        (director_name,)
    )

    return cursor.lastrowid


@app.route("/")
def home():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            f.id,
            f.title_original,
            f.title_russian,
            d.full_name AS director,
            f.production_year,
            f.age_rating,
            f.notes,

            GROUP_CONCAT(
                DISTINCT CONCAT(
                    fe.name,
                    ' (',
                    fe.year,
                    ')'
                )
                ORDER BY fe.year DESC, fe.name
                SEPARATOR ', '
            ) AS festivals

        FROM films f

        LEFT JOIN directors d
            ON f.director_id = d.id

        LEFT JOIN festival_films ff
            ON f.id = ff.film_id

        LEFT JOIN festivals fe
            ON ff.festival_id = fe.id

        GROUP BY
            f.id,
            f.title_original,
            f.title_russian,
            d.full_name,
            f.production_year,
            f.age_rating,
            f.notes

        ORDER BY f.id DESC
    """)

    films = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "index.html",
        films=films,
        is_admin=session.get("admin", False)
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin"):
        return redirect(url_for("home"))

    if request.method == "POST":
        entered_password = request.form.get(
            "password",
            ""
        )

        admin_password = os.getenv(
            "ADMIN_PASSWORD",
            ""
        )

        if (
            admin_password
            and hmac.compare_digest(
                entered_password,
                admin_password
            )
        ):
            session["admin"] = True

            flash(
                "Вы вошли как администратор.",
                "success"
            )

            return redirect(url_for("home"))

        flash(
            "Неверный пароль.",
            "error"
        )

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()

    flash(
        "Вы вышли из режима администратора.",
        "success"
    )

    return redirect(url_for("home"))


@app.route(
    "/add-film",
    methods=["GET", "POST"]
)
@admin_required
def add_film():
    if request.method == "POST":

        title_original = request.form.get(
            "title_original",
            ""
        ).strip()

        title_russian = request.form.get(
            "title_russian",
            ""
        ).strip()

        director_name = request.form.get(
            "director",
            ""
        ).strip()

        production_year = (
            request.form.get("production_year")
            or None
        )

        duration_minutes = (
            request.form.get("duration_minutes")
            or None
        )

        country = request.form.get(
            "country",
            ""
        ).strip()

        age_rating = request.form.get(
            "age_rating",
            ""
        ).strip()

        synopsis = request.form.get(
            "synopsis",
            ""
        ).strip()

        notes = request.form.get(
            "notes",
            ""
        ).strip()

        festival_ids = request.form.getlist(
            "festival_ids"
        )

        connection = get_connection()
        cursor = connection.cursor()

        try:
            director_id = get_or_create_director(
                cursor,
                director_name
            )

            cursor.execute(
                """
                INSERT INTO films (
                    title_original,
                    title_russian,
                    production_year,
                    duration_minutes,
                    country,
                    synopsis,
                    notes,
                    director_id,
                    age_rating
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    title_original,
                    title_russian,
                    production_year,
                    duration_minutes,
                    country,
                    synopsis,
                    notes,
                    director_id,
                    age_rating
                )
            )

            film_id = cursor.lastrowid

            for festival_id in festival_ids:
                cursor.execute(
                    """
                    INSERT INTO festival_films (
                        festival_id,
                        film_id
                    )
                    VALUES (%s, %s)
                    """,
                    (
                        festival_id,
                        film_id
                    )
                )

            connection.commit()

            flash(
                "Фильм успешно добавлен.",
                "success"
            )

        except Exception:
            connection.rollback()
            raise

        finally:
            cursor.close()
            connection.close()

        return redirect(url_for("home"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            id,
            name,
            year
        FROM festivals
        ORDER BY
            year DESC,
            name
    """)

    festivals = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "add_film.html",
        festivals=festivals
    )


@app.route(
    "/edit-film/<int:film_id>",
    methods=["GET", "POST"]
)
@admin_required
def edit_film(film_id):
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    if request.method == "POST":

        title_original = request.form.get(
            "title_original",
            ""
        ).strip()

        title_russian = request.form.get(
            "title_russian",
            ""
        ).strip()

        director_name = request.form.get(
            "director",
            ""
        ).strip()

        production_year = (
            request.form.get("production_year")
            or None
        )

        duration_minutes = (
            request.form.get("duration_minutes")
            or None
        )

        country = request.form.get(
            "country",
            ""
        ).strip()

        age_rating = request.form.get(
            "age_rating",
            ""
        ).strip()

        synopsis = request.form.get(
            "synopsis",
            ""
        ).strip()

        notes = request.form.get(
            "notes",
            ""
        ).strip()

        festival_ids = request.form.getlist(
            "festival_ids"
        )

        try:
            director_id = get_or_create_director(
                cursor,
                director_name
            )

            cursor.execute(
                """
                UPDATE films
                SET
                    title_original = %s,
                    title_russian = %s,
                    production_year = %s,
                    duration_minutes = %s,
                    country = %s,
                    synopsis = %s,
                    notes = %s,
                    director_id = %s,
                    age_rating = %s
                WHERE id = %s
                """,
                (
                    title_original,
                    title_russian,
                    production_year,
                    duration_minutes,
                    country,
                    synopsis,
                    notes,
                    director_id,
                    age_rating,
                    film_id
                )
            )

            cursor.execute(
                """
                DELETE FROM festival_films
                WHERE film_id = %s
                """,
                (film_id,)
            )

            for festival_id in festival_ids:
                cursor.execute(
                    """
                    INSERT INTO festival_films (
                        festival_id,
                        film_id
                    )
                    VALUES (%s, %s)
                    """,
                    (
                        festival_id,
                        film_id
                    )
                )

            connection.commit()

            flash(
                "Изменения сохранены.",
                "success"
            )

        except Exception:
            connection.rollback()
            raise

        finally:
            cursor.close()
            connection.close()

        return redirect(url_for("home"))

    cursor.execute(
        """
        SELECT
            f.id,
            f.title_original,
            f.title_russian,
            f.production_year,
            f.duration_minutes,
            f.country,
            f.synopsis,
            f.notes,
            f.age_rating,
            d.full_name AS director

        FROM films f

        LEFT JOIN directors d
            ON f.director_id = d.id

        WHERE f.id = %s
        """,
        (film_id,)
    )

    film = cursor.fetchone()

    if not film:
        cursor.close()
        connection.close()

        return "Фильм не найден", 404

    cursor.execute("""
        SELECT
            id,
            name,
            year
        FROM festivals
        ORDER BY
            year DESC,
            name
    """)

    festivals = cursor.fetchall()

    cursor.execute(
        """
        SELECT festival_id
        FROM festival_films
        WHERE film_id = %s
        """,
        (film_id,)
    )

    selected_rows = cursor.fetchall()

    selected_festival_ids = {
        row["festival_id"]
        for row in selected_rows
    }

    cursor.close()
    connection.close()

    return render_template(
        "edit_film.html",
        film=film,
        festivals=festivals,
        selected_festival_ids=selected_festival_ids
    )


@app.route(
    "/delete-film/<int:film_id>",
    methods=["POST"]
)
@admin_required
def delete_film(film_id):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            DELETE FROM festival_films
            WHERE film_id = %s
            """,
            (film_id,)
        )

        cursor.execute(
            """
            DELETE FROM films
            WHERE id = %s
            """,
            (film_id,)
        )

        connection.commit()

        flash(
            "Фильм удалён.",
            "success"
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("home"))


@app.route(
    "/add-festival",
    methods=["GET", "POST"]
)
@admin_required
def add_festival():
    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        year = (
            request.form.get("year")
            or None
        )

        city = request.form.get(
            "city",
            ""
        ).strip()

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id
            FROM festivals
            WHERE LOWER(name) = LOWER(%s)
            AND year = %s
            LIMIT 1
            """,
            (
                name,
                year
            )
        )

        existing_festival = cursor.fetchone()

        if existing_festival:
            flash(
                "Такой фестиваль за этот год уже существует.",
                "error"
            )

            cursor.close()
            connection.close()

            return redirect(
                url_for("add_festival")
            )

        cursor.execute(
            """
            INSERT INTO festivals (
                name,
                year,
                city
            )
            VALUES (%s, %s, %s)
            """,
            (
                name,
                year,
                city
            )
        )

        connection.commit()

        cursor.close()
        connection.close()

        flash(
            "Фестиваль успешно добавлен.",
            "success"
        )

        return redirect(url_for("home"))

    return render_template(
        "add_festival.html"
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=True
    )