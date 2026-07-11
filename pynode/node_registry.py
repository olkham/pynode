"""Static node-type registries built once at import time.

Node classes are static for the lifetime of the process, so everything here
(the reference engine used for introspection, the node-types cache served by
/api/node-types, and the api_routes / sse_handlers registries used for
dynamic route registration and SSE broadcasting) is safely shared by every
Flask app / WorkflowManager instance.
"""

import logging

from pynode.workflow_engine import WorkflowEngine
from pynode import nodes

logger = logging.getLogger(__name__)


def create_workflow_engine():
    """Create a new WorkflowEngine with all node types registered."""
    engine = WorkflowEngine()
    for node_class in nodes.get_all_node_types():
        engine.register_node_type(node_class)
    return engine


# Reference engine for node type introspection only
reference_engine = create_workflow_engine()

# Cache for node types (built once at startup or on first request)
_node_types_cache = None


def build_node_types_cache():
    """Build the node types cache from registered node types."""
    global _node_types_cache

    from pynode.nodes.base_node import BaseNode
    base_properties = getattr(BaseNode, 'properties', [])

    # Define category ordering
    category_order = [
        'common',
        'node probes',
        'logic',
        'function',
        'input',
        'output',
        'vision',
        'analysis',
        'network',
        'OpenCV'
    ]

    node_types = []
    for name, node_class in reference_engine.node_types.items():
        # Skip ErrorNode - it's a system node that shouldn't be manually added
        if node_class.hidden:
            continue

        display_name = getattr(node_class, 'display_name', name)
        icon = getattr(node_class, 'icon', '◆')
        category = getattr(node_class, 'category', 'custom')
        color = getattr(node_class, 'color', '#2d2d30')
        border_color = getattr(node_class, 'border_color', '#555')
        text_color = getattr(node_class, 'text_color', '#d4d4d4')
        input_count = getattr(node_class, 'input_count', 1)
        output_count = getattr(node_class, 'output_count', 1)

        # Handle callable properties (get_properties classmethod)
        if hasattr(node_class, 'get_properties') and callable(node_class.get_properties):
            node_properties = node_class.get_properties()
        else:
            node_properties = getattr(node_class, 'properties', [])

        # Ensure node_properties is iterable (list or tuple)
        if not isinstance(node_properties, (list, tuple)):
            node_properties = []

        # Get property names from node-specific properties to avoid duplicates
        node_prop_names = {prop.get('name') for prop in node_properties if isinstance(prop, dict)}

        # Add base properties that aren't overridden by node-specific properties
        merged_properties = [prop for prop in base_properties if prop.get('name') not in node_prop_names]
        # Add all node-specific properties
        merged_properties.extend(node_properties)

        ui_component = getattr(node_class, 'ui_component', None)
        ui_component_config = getattr(node_class, 'ui_component_config', {})
        info = getattr(node_class, 'info', '')

        node_types.append({
            'type': name,
            'name': display_name,
            'icon': icon,
            'category': category,
            'color': color,
            'borderColor': border_color,
            'textColor': text_color,
            'inputCount': input_count,
            'outputCount': output_count,
            'properties': merged_properties,
            'uiComponent': ui_component,
            'uiComponentConfig': ui_component_config,
            'info': info
        })

    # Sort node types by category order, then by name within each category
    def get_category_sort_key(node_type):
        category = node_type['category']
        try:
            # Categories in the order list get their index
            order_index = category_order.index(category)
        except ValueError:
            # Categories not in the list go to the end (third party)
            order_index = len(category_order)
        return (order_index, node_type['name'])

    node_types.sort(key=get_category_sort_key)

    _node_types_cache = node_types
    return _node_types_cache


def get_node_types():
    """Return the node-types cache, building it on first use if needed."""
    if _node_types_cache is None:
        build_node_types_cache()
    return _node_types_cache


# Build a registry of node types that have SSE handlers
# Maps node_type_name -> list of sse_handler defs
sse_handler_registry = {}

# Build a registry of node types that have api_routes
# Maps node_type_name -> list of route defs
api_route_registry = {}


def _build_node_registries():
    """Scan all node classes and build registries for API routes and SSE handlers."""
    for node_class in nodes.get_all_node_types():
        node_type_name = node_class.__name__

        api_routes = getattr(node_class, 'api_routes', [])
        if api_routes:
            api_route_registry[node_type_name] = api_routes

        sse_handlers = getattr(node_class, 'sse_handlers', [])
        if sse_handlers:
            sse_handler_registry[node_type_name] = sse_handlers


# Build caches/registries at import
build_node_types_cache()
_build_node_registries()
