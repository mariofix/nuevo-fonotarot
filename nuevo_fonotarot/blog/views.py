"""Views for the blog blueprint."""

from flask import abort, render_template

from ..models import BlogPost

from . import blog_bp


@blog_bp.route("/")
def index():
    """List all published blog posts, newest first."""
    posts = (
        BlogPost.query.filter_by(published=True)
        .order_by(BlogPost.published_at.desc())
        .all()
    )
    return render_template("blog/index.html", posts=posts)


@blog_bp.route("/<slug>")
def detail(slug: str):
    """Display a single published blog post."""
    post = BlogPost.query.filter_by(slug=slug, published=True).first()
    if post is None:
        abort(404)
    return render_template("blog/detail.html", post=post)
