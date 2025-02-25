import os
import logging
import sys
from pathlib import Path
import importlib.resources
from quart import Quart
from markdown2 import markdown
from ..database import DatabaseManager
from .database_extension import db

# Setup logging
logger = logging.getLogger(__name__)

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# File handler for web operations
web_handler = logging.FileHandler('logs/web.log')
web_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(web_handler)

# File handler for template debugging
template_handler = logging.FileHandler('logs/templates.log')
template_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Set log level based on DEBUG_LOGS
if os.getenv('DEBUG_LOGS', 'false').lower() == 'true':
    logger.setLevel(logging.INFO)
    template_handler.setLevel(logging.INFO)
else:
    logger.setLevel(logging.CRITICAL)
    template_handler.setLevel(logging.CRITICAL)

# Add template handler to the template logger
template_logger = logging.getLogger('template_debug')
template_logger.addHandler(template_handler)
template_logger.propagate = False

# Disable propagation to prevent stdout logging
logger.propagate = False

# Environment variables
WEB_UI_ENABLED = os.getenv('WEB_UI_ENABLED', 'false').lower() == 'true'
WEB_UI_PORT = int(os.getenv('WEB_UI_PORT', '8050'))
WEB_UI_HOST = os.getenv('WEB_UI_HOST', '127.0.0.1')


def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
        template_logger.info(f"Running in PyInstaller environment. MEIPASS: {base_path}")
    except Exception:
        # Try to find the package using importlib.resources (Python 3.9+)
        try:
            # Get the root package name from relative_path (e.g., "mcp_perplexity" from "mcp_perplexity/web/templates")
            root_package = relative_path.split('/')[0]
            
            # Try to find the package root using importlib
            template_logger.info(f"Trying to find package path for {root_package}")
            package_path = importlib.resources.files(root_package)
            if package_path:
                # If package found, use its path and append the remaining parts of relative_path
                relative_parts = relative_path.split('/')
                base_path = package_path.parent
                template_logger.info(f"Found package path: {base_path}")
            else:
                # Fall back to current directory if package not found
                base_path = os.path.abspath(".")
                template_logger.info(f"Package path not found. Using current directory: {base_path}")
        except (ImportError, ModuleNotFoundError, ValueError):
            # If importlib.resources approach fails, fall back to current directory
            base_path = os.path.abspath(".")
            template_logger.info(f"Running in development environment. Base path: {base_path}")
    
    # Try multiple possible locations for the templates
    paths_to_try = [
        os.path.join(base_path, relative_path),
        os.path.join(base_path, "src", relative_path),
        os.path.join(base_path, relative_path.split('/', 1)[1] if '/' in relative_path else relative_path)
    ]
    
    # Log all paths we're trying
    for i, path in enumerate(paths_to_try):
        template_logger.info(f"Trying path {i+1}: {path}")
        if os.path.exists(path):
            template_logger.info(f"Path exists: {path}")
            if os.path.isdir(path):
                template_logger.info(f"Directory contents: {os.listdir(path)}")
            return path
    
    # If none of the paths worked, return the original path calculation
    full_path = os.path.join(base_path, relative_path)
    template_logger.info(f"No alternative paths found. Using original path: {full_path}")
    template_logger.info(f"Path exists: {os.path.exists(full_path)}")
    if os.path.exists(full_path) and os.path.isdir(full_path):
        template_logger.info(f"Directory contents: {os.listdir(full_path)}")
    
    return full_path


def create_app():
    if not WEB_UI_ENABLED:
        logger.info("Web UI is disabled via environment variables")
        return None

    try:
        # Initialize Quart with template folder path
        template_path = get_resource_path('mcp_perplexity/web/templates')
        app = Quart(__name__, template_folder=template_path)

        # Add markdown filter
        def custom_markdown_filter(text):
            # Handle <think> tags preservation and transformation to collapsible elements
            import re
            import html
            
            # First, let's log the original text for debugging
            template_logger.info(f"Original text before processing: {text[:100]}...")
            
            # Extract and save <think> blocks
            think_pattern = re.compile(r'<think>(.*?)</think>', re.DOTALL)
            think_matches = think_pattern.findall(text)
            
            # If no think blocks found, just process markdown normally
            if not think_matches:
                return markdown(text, extras=['fenced-code-blocks', 'tables'])
            
            # Replace each <think> block with a unique placeholder
            # Use a format that's unlikely to be affected by markdown processing
            for i, content in enumerate(think_matches):
                placeholder = f"THINKBLOCK{i}PLACEHOLDER"
                text = text.replace(f"<think>{content}</think>", placeholder)
            
            # Process markdown
            html_content = markdown(text, extras=['fenced-code-blocks', 'tables'])
            template_logger.info(f"After markdown processing: {html_content[:100]}...")
            
            # Restore <think> blocks as collapsible details elements
            for i, content in enumerate(think_matches):
                placeholder = f"THINKBLOCK{i}PLACEHOLDER"
                # Process the content with markdown
                processed_content = markdown(content, extras=['fenced-code-blocks', 'tables'])
                
                # Create a collapsible details element
                details_element = (
                    f'<details class="think">'
                    f'<summary>Thought process</summary>'
                    f'<div class="think-content">{processed_content}</div>'
                    f'</details>'
                )
                
                # Try different possible formats the placeholder might have
                if placeholder in html_content:
                    html_content = html_content.replace(placeholder, details_element)
                elif f"<p>{placeholder}</p>" in html_content:
                    html_content = html_content.replace(f"<p>{placeholder}</p>", details_element)
                else:
                    # If we can't find the exact placeholder, try a more aggressive approach
                    template_logger.info(f"Placeholder {placeholder} not found in exact form, trying regex")
                    pattern = re.compile(fr'{placeholder}|<p>\s*{placeholder}\s*</p>', re.IGNORECASE)
                    html_content = pattern.sub(details_element, html_content)
            
            template_logger.info(f"Final HTML after restoring think blocks: {html_content[:100]}...")
            return html_content
            
        app.jinja_env.filters['markdown'] = custom_markdown_filter

        # Initialize database extension
        db.init_app(app)

        # Register routes
        from .routes import register_routes
        register_routes(app)

        logger.info(
            f"Web UI initialized successfully on {WEB_UI_HOST}:{WEB_UI_PORT}")
        return app
    except Exception as e:
        logger.error(f"Failed to initialize web UI: {e}")
        return None
