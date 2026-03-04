"""Blueprint for database-backed content: blog posts and static pages."""

from .views import blog_bp, content_bp

__all__ = ["blog_bp", "content_bp"]
