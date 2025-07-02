from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from datetime import date
import psycopg2
import psycopg2.extras
import os
import logging
from decimal import Decimal

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration - same as main app
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://manga_user:manga_password@localhost:5433/manga_db"
)


def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None


# ====================== DASHBOARD ======================


@app.route("/")
def dashboard():
    """Admin dashboard with statistics"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return render_template("admin/error.html")

    try:
        with conn.cursor() as cur:
            # Get statistics
            stats = {}

            cur.execute("SELECT COUNT(*) FROM manga")
            stats["manga_count"] = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM chapter")
            stats["chapter_count"] = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM author")
            stats["author_count"] = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM tag")
            stats["tag_count"] = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM pages")
            stats["page_count"] = cur.fetchone()[0]

            # Recent activity
            cur.execute("""
                SELECT name_english, name_romanized, name_original, created_at
                FROM manga 
                ORDER BY created_at DESC 
                LIMIT 5
            """)
            recent_manga = cur.fetchall()

            return render_template(
                "admin/dashboard.html", stats=stats, recent_manga=recent_manga
            )

    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        flash(f"Error loading dashboard: {str(e)}", "error")
        return render_template("admin/error.html")
    finally:
        conn.close()


# ====================== MANGA CRUD ======================


@app.route("/manga")
def manga_list():
    """List all manga with search"""
    search = request.args.get("search", "")
    page = int(request.args.get("page", 1))
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return render_template("admin/error.html")

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Build query with search
            where_clause = ""
            params = []

            if search:
                where_clause = """
                    WHERE LOWER(COALESCE(name_english, name_romanized, name_original)) 
                    LIKE LOWER(%s)
                """
                params.append(f"%{search}%")

            # Get total count
            count_query = f"SELECT COUNT(*) FROM manga {where_clause}"
            cur.execute(count_query, params)
            total = cur.fetchone()[0]

            # Get manga list
            query = f"""
                SELECT manga_id, name_english, name_romanized, name_original, 
                       manga_status, started_publishing, created_at
                FROM manga {where_clause}
                ORDER BY COALESCE(name_english, name_romanized, name_original)
                LIMIT %s OFFSET %s
            """
            params.extend([per_page, offset])
            cur.execute(query, params)
            manga_list = cur.fetchall()

            # Calculate pagination
            total_pages = (total + per_page - 1) // per_page

            return render_template(
                "admin/manga/list.html",
                manga_list=manga_list,
                search=search,
                page=page,
                total_pages=total_pages,
                total=total,
            )

    except Exception as e:
        logger.error(f"Manga list error: {e}")
        flash(f"Error loading manga list: {str(e)}", "error")
        return render_template("admin/error.html")
    finally:
        conn.close()


@app.route("/manga/new", methods=["GET", "POST"])
def manga_new():
    """Create new manga"""
    if request.method == "GET":
        return render_template("admin/manga/form.html", manga=None)

    # Handle POST request
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor() as cur:
            # Insert manga
            cur.execute(
                """
                INSERT INTO manga (name_original, name_romanized, name_english, 
                                 manga_status, started_publishing, ended_publishing, cover_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING manga_id
            """,
                (
                    request.form.get("name_original") or None,
                    request.form.get("name_romanized") or None,
                    request.form.get("name_english") or None,
                    request.form.get("manga_status", "unknown"),
                    request.form.get("started_publishing") or None,
                    request.form.get("ended_publishing") or None,
                    request.form.get("cover_path") or None,
                ),
            )
            manga_id = cur.fetchone()[0]
            conn.commit()

            flash("Manga created successfully!", "success")
            return redirect(url_for("manga_edit", manga_id=manga_id))

    except Exception as e:
        conn.rollback()
        logger.error(f"Manga creation error: {e}")
        flash(f"Error creating manga: {str(e)}", "error")
        return render_template("admin/manga/form.html", manga=None)
    finally:
        conn.close()


@app.route("/manga/<int:manga_id>/authors/<int:author_id>/remove", methods=["POST"])
def manga_remove_author(manga_id, author_id):
    """Remove author from manga"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_edit", manga_id=manga_id))

    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM writes WHERE author_id = %s AND manga_id = %s",
                (author_id, manga_id),
            )
            conn.commit()
            flash("Author removed successfully!", "success")

    except Exception as e:
        conn.rollback()
        logger.error(f"Author removal error: {e}")
        flash(f"Error removing author: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for("manga_edit", manga_id=manga_id))


@app.route("/manga/<int:manga_id>/languages/<language_id>/remove", methods=["POST"])
def manga_remove_language(manga_id, language_id):
    """Remove language support from manga"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_edit", manga_id=manga_id))

    try:
        with conn.cursor() as cur:
            # Check if there are chapters translated to this language
            cur.execute(
                """
                SELECT COUNT(*) FROM translated_to tt
                JOIN chapter c ON tt.chapter_id = c.chapter_id
                WHERE c.manga_id = %s AND tt.language_id = %s
            """,
                (manga_id, language_id),
            )

            count = cur.fetchone()[0]
            if count > 0:
                flash(
                    f"Cannot remove language: {count} chapters are translated to this language. Remove translations first.",
                    "error",
                )
                return redirect(url_for("manga_edit", manga_id=manga_id))

            cur.execute(
                "DELETE FROM supports WHERE language_id = %s AND manga_id = %s",
                (language_id, manga_id),
            )
            conn.commit()
            flash("Language removed successfully!", "success")

    except Exception as e:
        conn.rollback()
        logger.error(f"Language removal error: {e}")
        flash(f"Error removing language: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for("manga_edit", manga_id=manga_id))


# ====================== CHAPTER TEMPLATES AND ROUTES ======================


@app.route("/chapters/<int:chapter_id>/edit", methods=["GET", "POST"])
def chapter_edit(chapter_id):
    """Edit existing chapter"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Get chapter and manga info
            cur.execute(
                """
                SELECT c.*, m.name_english, m.name_romanized, m.name_original
                FROM chapter c
                JOIN manga m ON c.manga_id = m.manga_id
                WHERE c.chapter_id = %s
            """,
                (chapter_id,),
            )
            chapter = cur.fetchone()

            if not chapter:
                flash("Chapter not found", "error")
                return redirect(url_for("manga_list"))

            if request.method == "GET":
                return render_template(
                    "admin/chapters/form.html", manga=chapter, chapter=chapter
                )

            else:  # POST request
                cur.execute(
                    """
                    UPDATE chapter 
                    SET chapter_num = %s, page_count = %s
                    WHERE chapter_id = %s
                """,
                    (
                        Decimal(request.form["chapter_num"]),
                        int(request.form.get("page_count", 0)) or None,
                        chapter_id,
                    ),
                )

                conn.commit()
                flash("Chapter updated successfully!", "success")
                return redirect(url_for("chapter_list", manga_id=chapter["manga_id"]))

    except psycopg2.IntegrityError:
        conn.rollback()
        flash("Chapter number already exists for this manga!", "error")
        return render_template(
            "admin/chapters/form.html", manga=chapter, chapter=chapter
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"Chapter edit error: {e}")
        flash(f"Error updating chapter: {str(e)}", "error")
        return redirect(url_for("manga_list"))
    finally:
        conn.close()


@app.route("/chapters/<int:chapter_id>/delete", methods=["POST"])
def chapter_delete(chapter_id):
    """Delete chapter"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor() as cur:
            # Get manga_id before deletion
            cur.execute(
                "SELECT manga_id FROM chapter WHERE chapter_id = %s", (chapter_id,)
            )
            result = cur.fetchone()

            if not result:
                flash("Chapter not found", "error")
                return redirect(url_for("manga_list"))

            manga_id = result[0]

            cur.execute("DELETE FROM chapter WHERE chapter_id = %s", (chapter_id,))
            conn.commit()
            flash("Chapter deleted successfully!", "success")
            return redirect(url_for("chapter_list", manga_id=manga_id))

    except Exception as e:
        conn.rollback()
        logger.error(f"Chapter deletion error: {e}")
        flash(f"Error deleting chapter: {str(e)}", "error")
        return redirect(url_for("manga_list"))
    finally:
        conn.close()


# ====================== TRANSLATION MANAGEMENT ======================


@app.route("/chapters/<int:chapter_id>/translations")
def chapter_translations(chapter_id):
    """Manage chapter translations"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Get chapter and manga info
            cur.execute(
                """
                SELECT c.*, m.name_english, m.name_romanized, m.name_original, m.manga_id
                FROM chapter c
                JOIN manga m ON c.manga_id = m.manga_id
                WHERE c.chapter_id = %s
            """,
                (chapter_id,),
            )
            chapter = cur.fetchone()

            if not chapter:
                flash("Chapter not found", "error")
                return redirect(url_for("manga_list"))

            # Get existing translations
            cur.execute(
                """
                SELECT tt.*, l.language_name_en
                FROM translated_to tt
                JOIN language l ON tt.language_id = l.language_id
                WHERE tt.chapter_id = %s
                ORDER BY l.language_name_en
            """,
                (chapter_id,),
            )
            translations = cur.fetchall()

            # Get available languages (languages supported by manga)
            cur.execute(
                """
                SELECT l.language_id, l.language_name_en
                FROM language l
                JOIN supports s ON l.language_id = s.language_id
                WHERE s.manga_id = %s
                AND l.language_id NOT IN (
                    SELECT language_id FROM translated_to WHERE chapter_id = %s
                )
                ORDER BY l.language_name_en
            """,
                (chapter["manga_id"], chapter_id),
            )
            available_languages = cur.fetchall()

            return render_template(
                "admin/translations/list.html",
                chapter=chapter,
                translations=translations,
                available_languages=available_languages,
            )

    except Exception as e:
        logger.error(f"Translation list error: {e}")
        flash(f"Error loading translations: {str(e)}", "error")
        return redirect(url_for("manga_list"))
    finally:
        conn.close()


@app.route("/chapters/<int:chapter_id>/translations/add", methods=["POST"])
def chapter_add_translation(chapter_id):
    """Add translation to chapter"""
    language_id = request.form.get("language_id")

    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("chapter_translations", chapter_id=chapter_id))

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO translated_to (language_id, chapter_id, translation_date, is_complete)
                VALUES (%s, %s, %s, %s)
            """,
                (
                    language_id,
                    chapter_id,
                    date.today(),
                    request.form.get("is_complete") == "on",
                ),
            )
            conn.commit()
            flash("Translation added successfully!", "success")

    except psycopg2.IntegrityError:
        conn.rollback()
        flash("Translation already exists for this language!", "warning")
    except Exception as e:
        conn.rollback()
        logger.error(f"Translation creation error: {e}")
        flash(f"Error adding translation: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for("chapter_translations", chapter_id=chapter_id))


@app.route(
    "/chapters/<int:chapter_id>/translations/<language_id>/remove", methods=["POST"]
)
def chapter_remove_translation(chapter_id, language_id):
    """Remove translation from chapter"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("chapter_translations", chapter_id=chapter_id))

    try:
        with conn.cursor() as cur:
            # Check if there are pages associated with this translation
            cur.execute(
                "SELECT COUNT(*) FROM pages WHERE chapter_id = %s AND language_id = %s",
                (chapter_id, language_id),
            )
            page_count = cur.fetchone()[0]

            if page_count > 0:
                flash(
                    f"Cannot remove translation: {page_count} pages exist for this translation. Delete pages first.",
                    "error",
                )
                return redirect(url_for("chapter_translations", chapter_id=chapter_id))

            cur.execute(
                "DELETE FROM translated_to WHERE chapter_id = %s AND language_id = %s",
                (chapter_id, language_id),
            )
            conn.commit()
            flash("Translation removed successfully!", "success")

    except Exception as e:
        conn.rollback()
        logger.error(f"Translation removal error: {e}")
        flash(f"Error removing translation: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for("chapter_translations", chapter_id=chapter_id))


# ====================== PAGE MANAGEMENT ======================


@app.route("/chapters/<int:chapter_id>/pages/<language_id>")
def page_list(chapter_id, language_id):
    """List pages for a chapter in specific language"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Get chapter, manga, and language info
            cur.execute(
                """
                SELECT c.*, m.name_english, m.name_romanized, m.name_original, m.manga_id,
                       l.language_name_en
                FROM chapter c
                JOIN manga m ON c.manga_id = m.manga_id
                JOIN language l ON l.language_id = %s
                WHERE c.chapter_id = %s
            """,
                (language_id, chapter_id),
            )
            chapter_info = cur.fetchone()

            if not chapter_info:
                flash("Chapter or language not found", "error")
                return redirect(url_for("manga_list"))

            # Check if translation exists
            cur.execute(
                "SELECT * FROM translated_to WHERE chapter_id = %s AND language_id = %s",
                (chapter_id, language_id),
            )
            translation = cur.fetchone()

            if not translation:
                flash("Translation does not exist for this chapter", "error")
                return redirect(url_for("chapter_translations", chapter_id=chapter_id))

            # Get pages
            cur.execute(
                """
                SELECT * FROM pages 
                WHERE chapter_id = %s AND language_id = %s
                ORDER BY page_num
            """,
                (chapter_id, language_id),
            )
            pages = cur.fetchall()

            return render_template(
                "admin/pages/list.html",
                chapter=chapter_info,
                pages=pages,
                language_id=language_id,
            )

    except Exception as e:
        logger.error(f"Page list error: {e}")
        flash(f"Error loading pages: {str(e)}", "error")
        return redirect(url_for("manga_list"))
    finally:
        conn.close()


@app.route(
    "/chapters/<int:chapter_id>/pages/<language_id>/new", methods=["GET", "POST"]
)
def page_new(chapter_id, language_id):
    """Create new page"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Get chapter info
            cur.execute(
                """
                SELECT c.*, m.name_english, m.name_romanized, m.name_original,
                       l.language_name_en
                FROM chapter c
                JOIN manga m ON c.manga_id = m.manga_id
                JOIN language l ON l.language_id = %s
                WHERE c.chapter_id = %s
            """,
                (language_id, chapter_id),
            )
            chapter_info = cur.fetchone()

            if not chapter_info:
                flash("Chapter not found", "error")
                return redirect(url_for("manga_list"))

            if request.method == "GET":
                # Get next page number
                cur.execute(
                    """
                    SELECT COALESCE(MAX(page_num), 0) + 1 
                    FROM pages 
                    WHERE chapter_id = %s AND language_id = %s
                """,
                    (chapter_id, language_id),
                )
                next_page_num = cur.fetchone()[0]

                return render_template(
                    "admin/pages/form.html",
                    chapter=chapter_info,
                    page=None,
                    language_id=language_id,
                    next_page_num=next_page_num,
                )

            else:  # POST request
                cur.execute(
                    """
                    INSERT INTO pages (page_num, page_path, chapter_id, language_id)
                    VALUES (%s, %s, %s, %s)
                    RETURNING page_id
                """,
                    (
                        int(request.form["page_num"]),
                        request.form.get("page_path") or None,
                        chapter_id,
                        language_id,
                    ),
                )

                conn.commit()

                flash("Page created successfully!", "success")
                return redirect(
                    url_for("page_list", chapter_id=chapter_id, language_id=language_id)
                )

    except psycopg2.IntegrityError:
        conn.rollback()
        flash("Page number already exists for this chapter and language!", "error")
        return render_template(
            "admin/pages/form.html",
            chapter=chapter_info,
            page=None,
            language_id=language_id,
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"Page creation error: {e}")
        flash(f"Error creating page: {str(e)}", "error")
        return redirect(
            url_for("page_list", chapter_id=chapter_id, language_id=language_id)
        )
    finally:
        conn.close()


# ====================== BULK OPERATIONS ======================


@app.route("/manga/<int:manga_id>/bulk-chapters", methods=["GET", "POST"])
def bulk_create_chapters(manga_id):
    """Bulk create chapters"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Get manga info
            cur.execute("SELECT * FROM manga WHERE manga_id = %s", (manga_id,))
            manga = cur.fetchone()

            if not manga:
                flash("Manga not found", "error")
                return redirect(url_for("manga_list"))

            if request.method == "GET":
                return render_template("admin/bulk/chapters.html", manga=manga)

            else:  # POST request
                start_chapter = int(request.form["start_chapter"])
                end_chapter = int(request.form["end_chapter"])

                if start_chapter > end_chapter:
                    flash(
                        "Start chapter must be less than or equal to end chapter",
                        "error",
                    )
                    return render_template("admin/bulk/chapters.html", manga=manga)

                created_count = 0
                skipped_count = 0

                for chapter_num in range(start_chapter, end_chapter + 1):
                    try:
                        cur.execute(
                            """
                            INSERT INTO chapter (chapter_num, manga_id)
                            VALUES (%s, %s)
                        """,
                            (Decimal(str(chapter_num)), manga_id),
                        )
                        created_count += 1
                    except psycopg2.IntegrityError:
                        # Chapter already exists, skip it
                        skipped_count += 1
                        conn.rollback()
                        conn = get_db_connection()  # Get new connection after rollback
                        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
                        continue

                conn.commit()
                flash(
                    f"Bulk operation completed! Created {created_count} chapters, skipped {skipped_count} existing chapters.",
                    "success",
                )
                return redirect(url_for("chapter_list", manga_id=manga_id))

    except Exception as e:
        conn.rollback()
        logger.error(f"Bulk chapter creation error: {e}")
        flash(f"Error creating chapters: {str(e)}", "error")
        return render_template("admin/bulk/chapters.html", manga=manga)
    finally:
        conn.close()


# ====================== DATA EXPORT ======================


@app.route("/export/manga")
def export_manga():
    """Export manga data as JSON"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("dashboard"))

    try:
        import json
        from flask import Response

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Get all manga with related data
            cur.execute("""
                SELECT 
                    m.*,
                    ARRAY_AGG(DISTINCT t.tag_name) FILTER (WHERE t.tag_name IS NOT NULL) as tags,
                    ARRAY_AGG(DISTINCT a.name_romanized || COALESCE(' (' || w.role || ')', '')) 
                        FILTER (WHERE a.name_romanized IS NOT NULL) as authors,
                    ARRAY_AGG(DISTINCT l.language_name_en) FILTER (WHERE l.language_name_en IS NOT NULL) as languages
                FROM manga m
                LEFT JOIN has h ON m.manga_id = h.manga_id
                LEFT JOIN tag t ON h.tag_id = t.tag_id
                LEFT JOIN writes w ON m.manga_id = w.manga_id
                LEFT JOIN author a ON w.author_id = a.author_id
                LEFT JOIN supports s ON m.manga_id = s.manga_id
                LEFT JOIN language l ON s.language_id = l.language_id
                GROUP BY m.manga_id
                ORDER BY m.manga_id
            """)

            manga_list = []
            for row in cur.fetchall():
                manga_data = dict(row)
                # Convert dates to strings
                if manga_data["started_publishing"]:
                    manga_data["started_publishing"] = manga_data[
                        "started_publishing"
                    ].isoformat()
                if manga_data["ended_publishing"]:
                    manga_data["ended_publishing"] = manga_data[
                        "ended_publishing"
                    ].isoformat()
                if manga_data["created_at"]:
                    manga_data["created_at"] = manga_data["created_at"].isoformat()
                if manga_data["updated_at"]:
                    manga_data["updated_at"] = manga_data["updated_at"].isoformat()

                manga_list.append(manga_data)

            # Create JSON response
            json_data = json.dumps(manga_list, indent=2, ensure_ascii=False)

            response = Response(
                json_data,
                mimetype="application/json",
                headers={
                    "Content-Disposition": "attachment; filename=manga_export.json"
                },
            )

            return response

    except Exception as e:
        logger.error(f"Export error: {e}")
        flash(f"Error exporting data: {str(e)}", "error")
        return redirect(url_for("dashboard"))
    finally:
        conn.close()


@app.route("/pages/<int:page_id>/edit", methods=["GET", "POST"])
def page_edit(page_id):
    """Edit existing page"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Get page, chapter, and manga info
            cur.execute(
                """
                SELECT p.*, c.chapter_num, c.manga_id,
                       m.name_english, m.name_romanized, m.name_original,
                       l.language_name_en
                FROM pages p
                JOIN chapter c ON p.chapter_id = c.chapter_id
                JOIN manga m ON c.manga_id = m.manga_id
                JOIN language l ON p.language_id = l.language_id
                WHERE p.page_id = %s
            """,
                (page_id,),
            )
            page = cur.fetchone()

            if not page:
                flash("Page not found", "error")
                return redirect(url_for("manga_list"))

            if request.method == "GET":
                return render_template(
                    "admin/pages/form.html",
                    chapter=page,
                    page=page,
                    language_id=page["language_id"],
                )

            else:  # POST request
                cur.execute(
                    """
                    UPDATE pages 
                    SET page_num = %s, page_path = %s
                    WHERE page_id = %s
                """,
                    (
                        int(request.form["page_num"]),
                        request.form.get("page_path") or None,
                        page_id,
                    ),
                )

                conn.commit()
                flash("Page updated successfully!", "success")
                return redirect(
                    url_for(
                        "page_list",
                        chapter_id=page["chapter_id"],
                        language_id=page["language_id"],
                    )
                )

    except psycopg2.IntegrityError:
        conn.rollback()
        flash("Page number already exists for this chapter and language!", "error")
        return render_template(
            "admin/pages/form.html",
            chapter=page,
            page=page,
            language_id=page["language_id"],
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"Page edit error: {e}")
        flash(f"Error updating page: {str(e)}", "error")
        return redirect(url_for("manga_list"))
    finally:
        conn.close()


@app.route("/pages/<int:page_id>/delete", methods=["POST"])
def page_delete(page_id):
    """Delete page"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor() as cur:
            # Get chapter and language info before deletion
            cur.execute(
                "SELECT chapter_id, language_id FROM pages WHERE page_id = %s",
                (page_id,),
            )
            result = cur.fetchone()

            if not result:
                flash("Page not found", "error")
                return redirect(url_for("manga_list"))

            chapter_id, language_id = result

            cur.execute("DELETE FROM pages WHERE page_id = %s", (page_id,))
            conn.commit()
            flash("Page deleted successfully!", "success")
            return redirect(
                url_for("page_list", chapter_id=chapter_id, language_id=language_id)
            )

    except Exception as e:
        conn.rollback()
        logger.error(f"Page deletion error: {e}")
        flash(f"Error deleting page: {str(e)}", "error")
        return redirect(url_for("manga_list"))
    finally:
        conn.close()


# ====================== UTILITY FUNCTIONS ======================


def validate_image_path(path):
    """Validate image path and check if file exists"""
    if not path:
        return True, None

    import os

    full_path = os.path.join(DATA_DIR, path)

    # Check if path is safe (no directory traversal)
    if ".." in path or path.startswith("/"):
        return False, "Invalid path: Directory traversal not allowed"

    # Check if file exists
    if not os.path.exists(full_path):
        return False, f"File not found: {path}"

    # Check if it's actually within DATA_DIR
    if not os.path.abspath(full_path).startswith(os.path.abspath(DATA_DIR)):
        return False, "Invalid path: File must be within data directory"

    return True, None


# ====================== ADVANCED SEARCH ======================


@app.route("/search")
def advanced_search():
    """Advanced search across all entities"""
    query = request.args.get("q", "")
    entity_type = request.args.get("type", "all")  # manga, author, tag, all

    if not query or len(query) < 2:
        return render_template(
            "admin/search.html", results={}, query=query, entity_type=entity_type
        )

    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return render_template(
            "admin/search.html", results={}, query=query, entity_type=entity_type
        )

    try:
        results = {}
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if entity_type in ["manga", "all"]:
                # Search manga
                cur.execute(
                    """
                    SELECT manga_id, name_english, name_romanized, name_original, manga_status
                    FROM manga
                    WHERE LOWER(COALESCE(name_english, name_romanized, name_original)) LIKE LOWER(%s)
                    ORDER BY COALESCE(name_english, name_romanized, name_original)
                    LIMIT 20
                """,
                    (f"%{query}%",),
                )
                results["manga"] = cur.fetchall()

            if entity_type in ["author", "all"]:
                # Search authors
                cur.execute(
                    """
                    SELECT author_id, name_romanized
                    FROM author
                    WHERE LOWER(name_romanized) LIKE LOWER(%s)
                    ORDER BY name_romanized
                    LIMIT 20
                """,
                    (f"%{query}%",),
                )
                results["authors"] = cur.fetchall()

            if entity_type in ["tag", "all"]:
                # Search tags
                cur.execute(
                    """
                    SELECT tag_id, tag_name
                    FROM tag
                    WHERE LOWER(tag_name) LIKE LOWER(%s)
                    ORDER BY tag_name
                    LIMIT 20
                """,
                    (f"%{query}%",),
                )
                results["tags"] = cur.fetchall()

        return render_template(
            "admin/search.html", results=results, query=query, entity_type=entity_type
        )

    except Exception as e:
        logger.error(f"Search error: {e}")
        flash(f"Error performing search: {str(e)}", "error")
        return render_template(
            "admin/search.html", results={}, query=query, entity_type=entity_type
        )
    finally:
        conn.close()


# ====================== DATA DIRECTORY UTILITIES ======================

# Set DATA_DIR constant
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ====================== HEALTH CHECK ======================


@app.route("/health")
def health():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.close()
            return {"status": "healthy", "database": "connected"}, 200
        else:
            return {"status": "unhealthy", "database": "disconnected"}, 503
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}, 503


@app.route("/manga/<int:manga_id>/edit", methods=["GET", "POST"])
def manga_edit(manga_id):
    """Edit existing manga"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if request.method == "GET":
                # Get manga details
                cur.execute("SELECT * FROM manga WHERE manga_id = %s", (manga_id,))
                manga = cur.fetchone()

                if not manga:
                    flash("Manga not found", "error")
                    return redirect(url_for("manga_list"))

                # Get associated tags
                cur.execute(
                    """
                    SELECT t.tag_id, t.tag_name 
                    FROM tag t
                    JOIN has h ON t.tag_id = h.tag_id
                    WHERE h.manga_id = %s
                    ORDER BY t.tag_name
                """,
                    (manga_id,),
                )
                manga_tags = cur.fetchall()

                # Get associated authors
                cur.execute(
                    """
                    SELECT a.author_id, a.name_romanized, w.role
                    FROM author a
                    JOIN writes w ON a.author_id = w.author_id
                    WHERE w.manga_id = %s
                    ORDER BY a.name_romanized
                """,
                    (manga_id,),
                )
                manga_authors = cur.fetchall()

                # Get supported languages
                cur.execute(
                    """
                    SELECT l.language_id, l.language_name_en
                    FROM language l
                    JOIN supports s ON l.language_id = s.language_id
                    WHERE s.manga_id = %s
                    ORDER BY l.language_name_en
                """,
                    (manga_id,),
                )
                manga_languages = cur.fetchall()

                return render_template(
                    "admin/manga/form.html",
                    manga=manga,
                    manga_tags=manga_tags,
                    manga_authors=manga_authors,
                    manga_languages=manga_languages,
                )

            else:  # POST request
                # Update manga
                cur.execute(
                    """
                    UPDATE manga 
                    SET name_original = %s, name_romanized = %s, name_english = %s,
                        manga_status = %s, started_publishing = %s, ended_publishing = %s,
                        cover_path = %s, updated_at = NOW()
                    WHERE manga_id = %s
                """,
                    (
                        request.form.get("name_original") or None,
                        request.form.get("name_romanized") or None,
                        request.form.get("name_english") or None,
                        request.form.get("manga_status", "unknown"),
                        request.form.get("started_publishing") or None,
                        request.form.get("ended_publishing") or None,
                        request.form.get("cover_path") or None,
                        manga_id,
                    ),
                )

                conn.commit()
                flash("Manga updated successfully!", "success")
                return redirect(url_for("manga_edit", manga_id=manga_id))

    except Exception as e:
        conn.rollback()
        logger.error(f"Manga edit error: {e}")
        flash(f"Error updating manga: {str(e)}", "error")
        return redirect(url_for("manga_list"))
    finally:
        conn.close()


@app.route("/manga/<int:manga_id>/delete", methods=["POST"])
def manga_delete(manga_id):
    """Delete manga"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM manga WHERE manga_id = %s", (manga_id,))
            conn.commit()
            flash("Manga deleted successfully!", "success")

    except Exception as e:
        conn.rollback()
        logger.error(f"Manga deletion error: {e}")
        flash(f"Error deleting manga: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for("manga_list"))


# ====================== TAG CRUD ======================


@app.route("/tags")
def tag_list():
    """List all tags"""
    search = request.args.get("search", "")

    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return render_template("admin/error.html")

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            query = """
                SELECT t.tag_id, t.tag_name, COUNT(h.manga_id) as manga_count
                FROM tag t
                LEFT JOIN has h ON t.tag_id = h.tag_id
                WHERE (%s = '' OR LOWER(t.tag_name) LIKE LOWER(%s))
                GROUP BY t.tag_id, t.tag_name
                ORDER BY t.tag_name
            """

            search_param = f"%{search}%"
            cur.execute(query, (search, search_param))
            tags = cur.fetchall()

            return render_template("admin/tags/list.html", tags=tags, search=search)

    except Exception as e:
        logger.error(f"Tag list error: {e}")
        flash(f"Error loading tags: {str(e)}", "error")
        return render_template("admin/error.html")
    finally:
        conn.close()


@app.route("/tags/new", methods=["GET", "POST"])
def tag_new():
    """Create new tag"""
    if request.method == "GET":
        return render_template("admin/tags/form.html", tag=None)

    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("tag_list"))

    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tag (tag_name) VALUES (%s) RETURNING tag_id",
                (request.form["tag_name"],),
            )
            conn.commit()
            flash("Tag created successfully!", "success")
            return redirect(url_for("tag_list"))

    except psycopg2.IntegrityError:
        conn.rollback()
        flash("Tag name already exists!", "error")
        return render_template("admin/tags/form.html", tag=None)
    except Exception as e:
        conn.rollback()
        logger.error(f"Tag creation error: {e}")
        flash(f"Error creating tag: {str(e)}", "error")
        return render_template("admin/tags/form.html", tag=None)
    finally:
        conn.close()


# ====================== AUTHOR CRUD ======================


@app.route("/authors")
def author_list():
    """List all authors"""
    search = request.args.get("search", "")

    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return render_template("admin/error.html")

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            query = """
                SELECT a.author_id, a.name_romanized, COUNT(w.manga_id) as manga_count
                FROM author a
                LEFT JOIN writes w ON a.author_id = w.author_id
                WHERE (%s = '' OR LOWER(a.name_romanized) LIKE LOWER(%s))
                GROUP BY a.author_id, a.name_romanized
                ORDER BY a.name_romanized
            """

            search_param = f"%{search}%"
            cur.execute(query, (search, search_param))
            authors = cur.fetchall()

            return render_template(
                "admin/authors/list.html", authors=authors, search=search
            )

    except Exception as e:
        logger.error(f"Author list error: {e}")
        flash(f"Error loading authors: {str(e)}", "error")
        return render_template("admin/error.html")
    finally:
        conn.close()


@app.route("/authors/new", methods=["GET", "POST"])
def author_new():
    """Create new author"""
    if request.method == "GET":
        return render_template("admin/authors/form.html", author=None)

    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("author_list"))

    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO author (name_romanized) VALUES (%s) RETURNING author_id",
                (request.form["name_romanized"],),
            )
            conn.commit()
            flash("Author created successfully!", "success")
            return redirect(url_for("author_list"))

    except Exception as e:
        conn.rollback()
        logger.error(f"Author creation error: {e}")
        flash(f"Error creating author: {str(e)}", "error")
        return render_template("admin/authors/form.html", author=None)
    finally:
        conn.close()


# ====================== SEARCH ENDPOINTS ======================


@app.route("/api/search/tags")
def search_tags():
    """Search tags for relationship management"""
    query = request.args.get("q", "")

    conn = get_db_connection()
    if not conn:
        return jsonify([])

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT tag_id, tag_name
                FROM tag
                WHERE LOWER(tag_name) LIKE LOWER(%s)
                ORDER BY tag_name
                LIMIT 20
            """,
                (f"%{query}%",),
            )

            tags = [
                {"id": row["tag_id"], "name": row["tag_name"]} for row in cur.fetchall()
            ]

            return jsonify(tags)

    except Exception as e:
        logger.error(f"Tag search error: {e}")
        return jsonify([])
    finally:
        conn.close()


@app.route("/api/search/authors")
def search_authors():
    """Search authors for relationship management"""
    query = request.args.get("q", "")

    conn = get_db_connection()
    if not conn:
        return jsonify([])

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT author_id, name_romanized
                FROM author
                WHERE LOWER(name_romanized) LIKE LOWER(%s)
                ORDER BY name_romanized
                LIMIT 20
            """,
                (f"%{query}%",),
            )

            authors = [
                {"id": row["author_id"], "name": row["name_romanized"]}
                for row in cur.fetchall()
            ]

            return jsonify(authors)

    except Exception as e:
        logger.error(f"Author search error: {e}")
        return jsonify([])
    finally:
        conn.close()


@app.route("/api/search/manga")
def search_manga():
    """Search manga for relationship management"""
    query = request.args.get("q", "")

    conn = get_db_connection()
    if not conn:
        return jsonify([])

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT manga_id, 
                       COALESCE(name_english, name_romanized, name_original) as title
                FROM manga
                WHERE LOWER(COALESCE(name_english, name_romanized, name_original)) 
                      LIKE LOWER(%s)
                ORDER BY title
                LIMIT 20
            """,
                (f"%{query}%",),
            )

            manga = [
                {"id": row["manga_id"], "title": row["title"]} for row in cur.fetchall()
            ]

            return jsonify(manga)

    except Exception as e:
        logger.error(f"Manga search error: {e}")
        return jsonify([])
    finally:
        conn.close()


# ====================== TAG CRUD (CONTINUED) ======================


@app.route("/tags/<int:tag_id>/edit", methods=["GET", "POST"])
def tag_edit(tag_id):
    """Edit existing tag"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("tag_list"))

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if request.method == "GET":
                cur.execute("SELECT * FROM tag WHERE tag_id = %s", (tag_id,))
                tag = cur.fetchone()

                if not tag:
                    flash("Tag not found", "error")
                    return redirect(url_for("tag_list"))

                return render_template("admin/tags/form.html", tag=tag)

            else:  # POST request
                cur.execute(
                    "UPDATE tag SET tag_name = %s WHERE tag_id = %s",
                    (request.form["tag_name"], tag_id),
                )
                conn.commit()
                flash("Tag updated successfully!", "success")
                return redirect(url_for("tag_list"))

    except psycopg2.IntegrityError:
        conn.rollback()
        flash("Tag name already exists!", "error")
        return render_template(
            "admin/tags/form.html",
            tag={"tag_id": tag_id, "tag_name": request.form["tag_name"]},
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"Tag edit error: {e}")
        flash(f"Error updating tag: {str(e)}", "error")
        return redirect(url_for("tag_list"))
    finally:
        conn.close()


@app.route("/tags/<int:tag_id>/delete", methods=["POST"])
def tag_delete(tag_id):
    """Delete tag"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("tag_list"))

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tag WHERE tag_id = %s", (tag_id,))
            conn.commit()
            flash("Tag deleted successfully!", "success")

    except Exception as e:
        conn.rollback()
        logger.error(f"Tag deletion error: {e}")
        flash(f"Error deleting tag: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for("tag_list"))


# ====================== AUTHOR CRUD (CONTINUED) ======================


@app.route("/authors/<int:author_id>/edit", methods=["GET", "POST"])
def author_edit(author_id):
    """Edit existing author"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("author_list"))

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if request.method == "GET":
                cur.execute("SELECT * FROM author WHERE author_id = %s", (author_id,))
                author = cur.fetchone()

                if not author:
                    flash("Author not found", "error")
                    return redirect(url_for("author_list"))

                return render_template("admin/authors/form.html", author=author)

            else:  # POST request
                cur.execute(
                    "UPDATE author SET name_romanized = %s WHERE author_id = %s",
                    (request.form["name_romanized"], author_id),
                )
                conn.commit()
                flash("Author updated successfully!", "success")
                return redirect(url_for("author_list"))

    except Exception as e:
        conn.rollback()
        logger.error(f"Author edit error: {e}")
        flash(f"Error updating author: {str(e)}", "error")
        return redirect(url_for("author_list"))
    finally:
        conn.close()


@app.route("/authors/<int:author_id>/delete", methods=["POST"])
def author_delete(author_id):
    """Delete author"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("author_list"))

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM author WHERE author_id = %s", (author_id,))
            conn.commit()
            flash("Author deleted successfully!", "success")

    except Exception as e:
        conn.rollback()
        logger.error(f"Author deletion error: {e}")
        flash(f"Error deleting author: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for("author_list"))


# ====================== CHAPTER CRUD ======================


@app.route("/manga/<int:manga_id>/chapters")
def chapter_list(manga_id):
    """List chapters for a manga"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Get manga info
            cur.execute("SELECT * FROM manga WHERE manga_id = %s", (manga_id,))
            manga = cur.fetchone()

            if not manga:
                flash("Manga not found", "error")
                return redirect(url_for("manga_list"))

            # Get chapters
            cur.execute(
                """
                SELECT c.*, COUNT(p.page_id) as page_count
                FROM chapter c
                LEFT JOIN pages p ON c.chapter_id = p.chapter_id
                WHERE c.manga_id = %s
                GROUP BY c.chapter_id
                ORDER BY c.chapter_num
            """,
                (manga_id,),
            )
            chapters = cur.fetchall()

            return render_template(
                "admin/chapters/list.html", manga=manga, chapters=chapters
            )

    except Exception as e:
        logger.error(f"Chapter list error: {e}")
        flash(f"Error loading chapters: {str(e)}", "error")
        return redirect(url_for("manga_list"))
    finally:
        conn.close()


@app.route("/manga/<int:manga_id>/chapters/new", methods=["GET", "POST"])
def chapter_new(manga_id):
    """Create new chapter"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_list"))

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Get manga info
            cur.execute("SELECT * FROM manga WHERE manga_id = %s", (manga_id,))
            manga = cur.fetchone()

            if not manga:
                flash("Manga not found", "error")
                return redirect(url_for("manga_list"))

            if request.method == "GET":
                return render_template(
                    "admin/chapters/form.html", manga=manga, chapter=None
                )

            else:  # POST request
                cur.execute(
                    """
                    INSERT INTO chapter (chapter_num, page_count, manga_id)
                    VALUES (%s, %s, %s)
                    RETURNING chapter_id
                """,
                    (
                        Decimal(request.form["chapter_num"]),
                        int(request.form.get("page_count", 0)) or None,
                        manga_id,
                    ),
                )

                conn.commit()

                flash("Chapter created successfully!", "success")
                return redirect(url_for("chapter_list", manga_id=manga_id))

    except psycopg2.IntegrityError:
        conn.rollback()
        flash("Chapter number already exists for this manga!", "error")
        return render_template("admin/chapters/form.html", manga=manga, chapter=None)
    except Exception as e:
        conn.rollback()
        logger.error(f"Chapter creation error: {e}")
        flash(f"Error creating chapter: {str(e)}", "error")
        return render_template("admin/chapters/form.html", manga=manga, chapter=None)
    finally:
        conn.close()


# ====================== RELATIONSHIP MANAGEMENT ======================


@app.route("/manga/<int:manga_id>/tags/add", methods=["POST"])
def manga_add_tag(manga_id):
    """Add tag to manga"""
    tag_id = request.form.get("tag_id")

    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_edit", manga_id=manga_id))

    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO has (tag_id, manga_id) VALUES (%s, %s)", (tag_id, manga_id)
            )
            conn.commit()
            flash("Tag added successfully!", "success")

    except psycopg2.IntegrityError:
        conn.rollback()
        flash("Tag already associated with this manga!", "warning")
    except Exception as e:
        conn.rollback()
        logger.error(f"Tag association error: {e}")
        flash(f"Error adding tag: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for("manga_edit", manga_id=manga_id))


@app.route("/manga/<int:manga_id>/tags/<int:tag_id>/remove", methods=["POST"])
def manga_remove_tag(manga_id, tag_id):
    """Remove tag from manga"""
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_edit", manga_id=manga_id))

    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM has WHERE tag_id = %s AND manga_id = %s",
                (tag_id, manga_id),
            )
            conn.commit()
            flash("Tag removed successfully!", "success")

    except Exception as e:
        conn.rollback()
        logger.error(f"Tag removal error: {e}")
        flash(f"Error removing tag: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for("manga_edit", manga_id=manga_id))


@app.route("/manga/<int:manga_id>/authors/add", methods=["POST"])
def manga_add_author(manga_id):
    """Add author to manga"""
    author_id = request.form.get("author_id")
    role = request.form.get("role", "author")

    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_edit", manga_id=manga_id))

    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO writes (author_id, manga_id, role) VALUES (%s, %s, %s)",
                (author_id, manga_id, role),
            )
            conn.commit()
            flash("Author added successfully!", "success")

    except psycopg2.IntegrityError:
        conn.rollback()
        flash("Author already associated with this manga in this role!", "warning")
    except Exception as e:
        conn.rollback()
        logger.error(f"Author association error: {e}")
        flash(f"Error adding author: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for("manga_edit", manga_id=manga_id))


@app.route("/manga/<int:manga_id>/languages/add", methods=["POST"])
def manga_add_language(manga_id):
    """Add language support to manga"""
    language_id = request.form.get("language_id")

    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("manga_edit", manga_id=manga_id))

    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO supports (language_id, manga_id) VALUES (%s, %s)",
                (language_id, manga_id),
            )
            conn.commit()
            flash("Language added successfully!", "success")

    except psycopg2.IntegrityError:
        conn.rollback()
        flash("Language already supported by this manga!", "warning")
    except Exception as e:
        conn.rollback()
        logger.error(f"Language association error: {e}")
        flash(f"Error adding language: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for("manga_edit", manga_id=manga_id))


# ====================== ERROR HANDLERS ======================


@app.errorhandler(404)
def not_found(error):
    return render_template(
        "admin/error.html",
        error_title="Page Not Found",
        error_message="The page you are looking for does not exist.",
    ), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template(
        "admin/error.html",
        error_title="Internal Server Error",
        error_message="An unexpected error occurred.",
    ), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
