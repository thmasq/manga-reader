from flask import Flask, render_template, request, jsonify
from datetime import datetime

app = Flask(__name__)

# Sample manga data
SAMPLE_MANGA = [
    {
        "id": 1,
        "title": "Attack on Titan",
        "rating": 9.2,
        "status": "completed",
        "language": "japanese",
        "tags": ["Action", "Drama", "Fantasy", "Military"],
        "publishDate": "2009-09-09",
    },
    {
        "id": 2,
        "title": "One Piece",
        "rating": 9.5,
        "status": "ongoing",
        "language": "japanese",
        "tags": ["Adventure", "Comedy", "Shounen", "Pirates"],
        "publishDate": "1997-07-22",
    },
    {
        "id": 3,
        "title": "Demon Slayer",
        "rating": 8.8,
        "status": "completed",
        "language": "japanese",
        "tags": ["Supernatural", "Historical", "Shounen"],
        "publishDate": "2016-02-15",
    },
    {
        "id": 4,
        "title": "Tower of God",
        "rating": 8.6,
        "status": "ongoing",
        "language": "english",
        "tags": ["Adventure", "Mystery", "Supernatural"],
        "publishDate": "2010-06-30",
    },
    {
        "id": 5,
        "title": "Solo Leveling",
        "rating": 9.1,
        "status": "completed",
        "language": "english",
        "tags": ["Action", "Adventure", "Fantasy"],
        "publishDate": "2018-03-04",
    },
    {
        "id": 6,
        "title": "Chainsaw Man",
        "rating": 8.9,
        "status": "ongoing",
        "language": "japanese",
        "tags": ["Action", "Comedy", "Supernatural"],
        "publishDate": "2018-12-03",
    },
    {
        "id": 7,
        "title": "My Hero Academia",
        "rating": 8.4,
        "status": "ongoing",
        "language": "japanese",
        "tags": ["Action", "School", "Superhero"],
        "publishDate": "2014-07-07",
    },
    {
        "id": 8,
        "title": "The God of High School",
        "rating": 8.2,
        "status": "hiatus",
        "language": "english",
        "tags": ["Action", "Martial Arts", "School"],
        "publishDate": "2011-04-08",
    },
    {
        "id": 9,
        "title": "Naruto",
        "rating": 8.7,
        "status": "completed",
        "language": "japanese",
        "tags": ["Action", "Martial Arts", "Ninja"],
        "publishDate": "1999-09-21",
    },
    {
        "id": 10,
        "title": "Death Note",
        "rating": 9.0,
        "status": "completed",
        "language": "japanese",
        "tags": ["Supernatural", "Thriller", "Psychological"],
        "publishDate": "2003-12-01",
    },
    {
        "id": 11,
        "title": "Vinland Saga",
        "rating": 9.3,
        "status": "ongoing",
        "language": "japanese",
        "tags": ["Action", "Adventure", "Historical"],
        "publishDate": "2005-04-13",
    },
    {
        "id": 12,
        "title": "Spy x Family",
        "rating": 8.6,
        "status": "ongoing",
        "language": "japanese",
        "tags": ["Action", "Comedy", "Family"],
        "publishDate": "2019-03-25",
    },
]


def filter_and_sort_manga(
    search_query="", status_filters=None, language_filters=None, sort_by="alphabetical"
):
    """Filter and sort manga based on provided criteria"""
    if status_filters is None:
        status_filters = []
    if language_filters is None:
        language_filters = []

    filtered = SAMPLE_MANGA.copy()

    # Apply search filter
    if search_query:
        search_query = search_query.lower().strip()
        filtered = [
            manga
            for manga in filtered
            if search_query in manga["title"].lower()
            or any(search_query in tag.lower() for tag in manga["tags"])
        ]

    # Apply status filter
    if status_filters:
        filtered = [manga for manga in filtered if manga["status"] in status_filters]

    # Apply language filter
    if language_filters:
        filtered = [
            manga for manga in filtered if manga["language"] in language_filters
        ]

    # Apply sorting
    if sort_by == "alphabetical":
        filtered.sort(key=lambda x: x["title"])
    elif sort_by == "reverse-alphabetical":
        filtered.sort(key=lambda x: x["title"], reverse=True)
    elif sort_by == "date-newest":
        filtered.sort(
            key=lambda x: datetime.strptime(x["publishDate"], "%Y-%m-%d"), reverse=True
        )
    elif sort_by == "date-oldest":
        filtered.sort(key=lambda x: datetime.strptime(x["publishDate"], "%Y-%m-%d"))
    elif sort_by == "rating":
        filtered.sort(key=lambda x: x["rating"], reverse=True)

    return filtered


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
    elif section_type == "curated":
        high_rated = [manga for manga in manga_list if manga["rating"] >= 9.0]
        return high_rated[:limit]
    return []


@app.route("/")
def index():
    """Main gallery page"""
    manga_list = filter_and_sort_manga()

    sections = {
        "trending": get_section_manga(manga_list, "trending"),
        "just_published": get_section_manga(manga_list, "just-published"),
        "curated": get_section_manga(manga_list, "curated"),
    }

    return render_template("gallery.html", sections=sections)


@app.route("/search")
def search():
    """HTMX endpoint for search and filtering"""
    search_query = request.args.get("search", "")
    status_filters = request.args.getlist("status")
    language_filters = request.args.getlist("language")
    sort_by = request.args.get("sort", "alphabetical")

    filtered_manga = filter_and_sort_manga(
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
            "curated": get_section_manga(filtered_manga, "curated"),
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
    """Individual manga details (placeholder for future implementation)"""
    manga = next((m for m in SAMPLE_MANGA if m["id"] == manga_id), None)
    if not manga:
        return "Manga not found", 404
    return jsonify(manga)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
