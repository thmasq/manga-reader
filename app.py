from flask import Flask, render_template, request, jsonify, send_from_directory, abort
from datetime import datetime
import psycopg2
import psycopg2.extras
import os
import logging

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://manga_user:manga_password@localhost:5432/manga_db"
)
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None


def init_db():
    """Initialize database connection and test it"""
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.close()
            logger.info("Database connection successful")
            return True
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        return False


def get_manga_list(
    search_query="",
    status_filters=None,
    language_filters=None,
    sort_by="alphabetical",
    limit=None,
):
    """Get filtered and sorted manga list from database"""
    if status_filters is None:
        status_filters = []
    if language_filters is None:
        language_filters = []

    conn = get_db_connection()
    if not conn:
        return []

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Base query with joins
            query = """
                SELECT DISTINCT
                    m.manga_id,
                    COALESCE(m.name_english, m.name_romanized, m.name_original) as title,
                    m.manga_status as status,
                    m.started_publishing as publish_date,
                    m.cover_path,
                    ARRAY_AGG(DISTINCT t.tag_name) FILTER (WHERE t.tag_name IS NOT NULL) as tags,
                    ARRAY_AGG(DISTINCT l.language_name_en) FILTER (WHERE l.language_name_en IS NOT NULL) as languages
                FROM manga m
                LEFT JOIN has h ON m.manga_id = h.manga_id
                LEFT JOIN tag t ON h.tag_id = t.tag_id
                LEFT JOIN supports s ON m.manga_id = s.manga_id
                LEFT JOIN language l ON s.language_id = l.language_id
                WHERE 1=1
            """

            params = []

            # Add search filter
            if search_query:
                query += """
                    AND (
                        LOWER(COALESCE(m.name_english, m.name_romanized, m.name_original)) LIKE LOWER(%s)
                        OR EXISTS (
                            SELECT 1 FROM has h2 
                            JOIN tag t2 ON h2.tag_id = t2.tag_id 
                            WHERE h2.manga_id = m.manga_id 
                            AND LOWER(t2.tag_name) LIKE LOWER(%s)
                        )
                    )
                """
                search_param = f"%{search_query}%"
                params.extend([search_param, search_param])

            # Add status filter
            if status_filters:
                placeholders = ",".join(["%s"] * len(status_filters))
                query += f" AND m.manga_status IN ({placeholders})"
                params.extend(status_filters)

            # Add language filter
            if language_filters:
                placeholders = ",".join(["%s"] * len(language_filters))
                query += f"""
                    AND EXISTS (
                        SELECT 1 FROM supports s2 
                        JOIN language l2 ON s2.language_id = l2.language_id
                        WHERE s2.manga_id = m.manga_id 
                        AND LOWER(l2.language_name_en) IN ({placeholders})
                    )
                """
                params.extend([lang.lower() for lang in language_filters])

            # Group by
            query += """
                GROUP BY m.manga_id, m.name_english, m.name_romanized, m.name_original,
                         m.manga_status, m.started_publishing, m.cover_path
            """

            # Add sorting
            if sort_by == "alphabetical":
                query += " ORDER BY title ASC"
            elif sort_by == "reverse-alphabetical":
                query += " ORDER BY title DESC"
            elif sort_by == "date-newest":
                query += " ORDER BY m.started_publishing DESC NULLS LAST"
            elif sort_by == "date-oldest":
                query += " ORDER BY m.started_publishing ASC NULLS LAST"
            # Add limit
            if limit:
                query += f" LIMIT {limit}"

            cur.execute(query, params)
            rows = cur.fetchall()

            manga_list = []
            for row in rows:
                manga = {
                    "id": row["manga_id"],
                    "title": row["title"] or "Unknown Title",
                    "status": row["status"] or "unknown",
                    "language": row["languages"][0].lower()
                    if row["languages"] and row["languages"][0]
                    else "unknown",
                    "tags": row["tags"] if row["tags"] and row["tags"][0] else [],
                    "publishDate": row["publish_date"].strftime("%Y-%m-%d")
                    if row["publish_date"]
                    else "2020-01-01",
                    "cover_path": row["cover_path"],
                }
                manga_list.append(manga)

            return manga_list

    except Exception as e:
        logger.error(f"Error fetching manga list: {e}")
        return []
    finally:
        conn.close()


def get_section_manga(manga_list, section_type, limit=6):
    """Get manga for specific sections"""
    if section_type == "trending":
        return manga_list[:limit]
    elif section_type == "just-published":
        sorted_by_date = sorted(
            manga_list,
            key=lambda x: datetime.strptime(x["publishDate"], "%Y-%m-%d"),
            reverse=True,
        )
        return sorted_by_date[:limit]
    return []


@app.route("/")
def index():
    """Main gallery page"""
    manga_list = get_manga_list()

    sections = {
        "trending": get_section_manga(manga_list, "trending"),
        "just_published": get_section_manga(manga_list, "just-published"),
    }

    return render_template("gallery.html", sections=sections)


@app.route("/search")
def search():
    """HTMX endpoint for search and filtering"""
    search_query = request.args.get("search", "")
    status_filters = request.args.getlist("status")
    language_filters = request.args.getlist("language")
    sort_by = request.args.get("sort", "alphabetical")

    filtered_manga = get_manga_list(
        search_query, status_filters, language_filters, sort_by
    )

    # Determine if we should show search results section
    show_search_results = bool(search_query or status_filters or language_filters)

    sections = {}
    if not show_search_results:
        # Show default sections when no filters applied
        sections = {
            "trending": get_section_manga(filtered_manga, "trending"),
            "just_published": get_section_manga(filtered_manga, "just-published"),
        }
    else:
        # Show search results
        sections = {
            "search_results": {"manga": filtered_manga, "count": len(filtered_manga)}
        }

    return render_template(
        "components/manga_sections.html",
        sections=sections,
        show_search_results=show_search_results,
    )


@app.route("/manga/<int:manga_id>")
def manga_detail(manga_id):
    """Individual manga details"""
    conn = get_db_connection()
    if not conn:
        return "Database connection error", 500

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Get manga details with tags and authors
            cur.execute(
                """
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
                WHERE m.manga_id = %s
                GROUP BY m.manga_id
            """,
                (manga_id,),
            )

            manga = cur.fetchone()
            if not manga:
                return "Manga not found", 404

            # Get chapters
            cur.execute(
                """
                SELECT c.*, 
                       ARRAY_AGG(DISTINCT l.language_name_en) FILTER (WHERE l.language_name_en IS NOT NULL) as available_languages
                FROM chapter c
                LEFT JOIN translated_to tt ON c.chapter_id = tt.chapter_id
                LEFT JOIN language l ON tt.language_id = l.language_id
                WHERE c.manga_id = %s
                GROUP BY c.chapter_id
                ORDER BY c.chapter_num
            """,
                (manga_id,),
            )

            chapters = cur.fetchall()

            manga_data = {
                "id": manga["manga_id"],
                "title": manga["name_english"]
                or manga["name_romanized"]
                or manga["name_original"],
                "original_title": manga["name_original"],
                "romanized_title": manga["name_romanized"],
                "status": manga["manga_status"],
                "started_publishing": manga["started_publishing"].strftime("%Y-%m-%d")
                if manga["started_publishing"]
                else None,
                "ended_publishing": manga["ended_publishing"].strftime("%Y-%m-%d")
                if manga["ended_publishing"]
                else None,
                "cover_path": manga["cover_path"],
                "tags": manga["tags"] if manga["tags"] and manga["tags"][0] else [],
                "authors": manga["authors"]
                if manga["authors"] and manga["authors"][0]
                else [],
                "languages": manga["languages"]
                if manga["languages"] and manga["languages"][0]
                else [],
                "chapters": [dict(chapter) for chapter in chapters] if chapters else [],
            }

            return jsonify(manga_data)

    except Exception as e:
        logger.error(f"Error fetching manga details: {e}")
        return "Internal server error", 500
    finally:
        conn.close()


@app.route("/images/<path:image_path>")
def serve_image(image_path):
    """Serve images from the data directory"""
    try:
        # Ensure the path is safe (no directory traversal)
        if ".." in image_path or image_path.startswith("/"):
            abort(404)

        full_path = os.path.join(DATA_DIR, image_path)

        # Check if file exists and is within DATA_DIR
        if not os.path.exists(full_path) or not os.path.abspath(full_path).startswith(
            os.path.abspath(DATA_DIR)
        ):
            abort(404)

        # Get the directory and filename
        directory = os.path.dirname(full_path)
        filename = os.path.basename(full_path)

        return send_from_directory(directory, filename)

    except Exception as e:
        logger.error(f"Error serving image {image_path}: {e}")
        abort(404)


@app.route("/manga/<int:manga_id>/cover")
def manga_cover(manga_id):
    """Get manga cover image"""
    conn = get_db_connection()
    if not conn:
        abort(500)

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT cover_path FROM manga WHERE manga_id = %s", (manga_id,))
            result = cur.fetchone()

            if not result or not result[0]:
                abort(404)

            return serve_image(result[0])

    except Exception as e:
        logger.error(f"Error fetching cover for manga {manga_id}: {e}")
        abort(404)
    finally:
        conn.close()


@app.route("/chapter/<int:chapter_id>/page/<int:page_num>")
def chapter_page(chapter_id, page_num):
    """Get specific page from a chapter"""
    language_id = request.args.get("lang", "en")

    conn = get_db_connection()
    if not conn:
        abort(500)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT page_path FROM pages 
                WHERE chapter_id = %s AND page_num = %s AND language_id = %s
            """,
                (chapter_id, page_num, language_id),
            )

            result = cur.fetchone()

            if not result or not result[0]:
                abort(404)

            return serve_image(result[0])

    except Exception as e:
        logger.error(f"Error fetching page {page_num} for chapter {chapter_id}: {e}")
        abort(404)
    finally:
        conn.close()


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


# Initialize database connection on startup
@app.before_request
def before_request():
    """Initialize database before first request"""
    if not hasattr(app, "db_initialized"):
        init_db()
        app.db_initialized = True


if __name__ == "__main__":
    # Initialize database
    if not init_db():
        logger.error("Failed to initialize database. Exiting.")
        exit(1)

    app.run(debug=True, host="0.0.0.0")
