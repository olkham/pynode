#!/usr/bin/env python3
"""
Factory module for creating inference engines
"""

import os
import sys
import logging
import importlib
import inspect

from flask import json

# Handle both standalone and module imports
try:
    from .engines.base_engine import BaseInferenceEngine
except ImportError:
    # If running as standalone script, add current directory to path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    
    try:
        from InferenceEngine.engines.base_engine import BaseInferenceEngine
    except ImportError:
        # Last resort: direct local imports
        sys.path.insert(0, current_dir)
        from engines.base_engine import BaseInferenceEngine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class InferenceEngineFactory:
    """Factory class for creating inference engine instances."""

    # Start with empty dictionaries - will be populated by auto-discovery
    _engine_types = {}
    _engine_display_names = {}
    _discovery_complete = False
    
    @classmethod
    def _discover_engines(cls):
        """Automatically discover and register engine classes from the engines folder"""
        if cls._discovery_complete:
            return
            
        logger.info("Starting automatic engine discovery...")
        
        # Get the engines directory path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        engines_dir = os.path.join(current_dir, 'engines')
        
        if not os.path.exists(engines_dir):
            logger.warning(f"Engines directory not found: {engines_dir}")
            cls._discovery_complete = True
            return
        
        # Files to skip during discovery
        skip_files = {
            '__init__.py',
            'base_engine.py',
            'example_engine_template.py',
            '__pycache__'
        }
        
        # Scan for Python files in the engines directory
        for filename in os.listdir(engines_dir):
            if filename in skip_files:
                continue
                
            if filename.endswith('.py'):
                module_name = filename[:-3]  # Remove .py extension
                
                try:
                    # Import the module
                    if __name__ == "__main__":
                        # Running as standalone script
                        sys.path.insert(0, engines_dir)
                        module = importlib.import_module(module_name)
                    else:
                        # Running as package - try multiple import strategies
                        module = None
                        import_errors = []
                        
                        # Strategy 1: Use __package__ to build the full path dynamically
                        # __package__ gives us something like 'nodes.InferenceNode.InferenceEngine'
                        if __package__:
                            try:
                                module = importlib.import_module(f'{__package__}.engines.{module_name}')
                            except ImportError as e:
                                import_errors.append(f"Package path ({__package__}): {e}")
                        
                        # Strategy 2: Relative import from current package
                        if module is None:
                            try:
                                module = importlib.import_module(f'.engines.{module_name}', package=__package__)
                            except ImportError as e:
                                import_errors.append(f"Relative with __package__: {e}")
                        
                        # Strategy 3: Direct import after adding to sys.path
                        if module is None:
                            try:
                                if engines_dir not in sys.path:
                                    sys.path.insert(0, engines_dir)
                                module = importlib.import_module(module_name)
                            except ImportError as e:
                                import_errors.append(f"Direct: {e}")
                        
                        if module is None:
                            logger.warning(f"Failed to import {module_name}: {import_errors}")
                            continue
                    
                    # Find engine classes in the module
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        # Check if it's a valid engine class
                        if (obj != BaseInferenceEngine and 
                            issubclass(obj, BaseInferenceEngine) and 
                            obj.__module__ == module.__name__):
                            
                            # Generate engine key from class name
                            engine_key = cls._class_name_to_key(name)
                            
                            # Register the engine
                            if engine_key not in cls._engine_types:
                                cls._engine_types[engine_key] = obj
                                
                                # Set display name
                                if hasattr(obj, 'display_name'):
                                    cls._engine_display_names[engine_key] = obj.display_name
                                else:
                                    cls._engine_display_names[engine_key] = engine_key.replace('_', ' ').title()
                                
                                logger.info(f"Auto-discovered engine: {engine_key} -> {obj.__name__} ({cls._engine_display_names[engine_key]})")
                            else:
                                logger.debug(f"Engine key '{engine_key}' already registered, skipping {obj.__name__}")
                
                except Exception as e:
                    logger.warning(f"Failed to import engine from {filename}: {e}")
                    continue
        
        cls._discovery_complete = True
        logger.info(f"Engine discovery complete. Found {len(cls._engine_types)} engines.")
    
    @classmethod
    def _class_name_to_key(cls, class_name: str) -> str:
        """
        Convert a class name to an engine key.
        
        Examples:
        - UltralyticsEngine -> ultralytics
        - GetiEngine -> geti
        - CustomObjectDetectionEngine -> custom_object_detection
        - MyAIEngine -> my_ai
        """
        # Remove common suffixes
        suffixes_to_remove = ['Engine', 'Inference', 'AI', 'Model']
        key = class_name
        
        for suffix in suffixes_to_remove:
            if key.endswith(suffix) and len(key) > len(suffix):
                key = key[:-len(suffix)]
                break
        
        # Convert CamelCase to snake_case
        result = []
        for i, char in enumerate(key):
            if char.isupper() and i > 0:
                result.append('_')
            result.append(char.lower())
        
        return ''.join(result)
    
    @classmethod
    def _initialize_display_names(cls):
        """Initialize display names from engine classes if not already set"""
        cls._discover_engines()  # Ensure discovery is complete
        
        for engine_type, engine_class in cls._engine_types.items():
            if engine_type not in cls._engine_display_names:
                if hasattr(engine_class, 'display_name'):
                    cls._engine_display_names[engine_type] = engine_class.display_name
                else:
                    cls._engine_display_names[engine_type] = engine_type.replace('_', ' ').title()
    
    @classmethod
    def create(cls, engine_type=None, **kwargs):
        """
        Create an inference engine instance.
        
        Args:
            engine_type: Type of engine ('ultralytics', 'geti', etc.)
            **kwargs: Additional parameters for the specific engine type
            
        Returns:
            BaseInferenceEngine: Configured engine instance
            
        Raises:
            ValueError: If engine_type is not supported
        """
        cls._discover_engines()  # Ensure engines are discovered
        
        if engine_type is None:
            engine_type = kwargs.pop('engine_type', None)
        
        if engine_type not in cls._engine_types:
            available_types = ', '.join(cls._engine_types.keys())
            raise ValueError(f"Unsupported engine type: {engine_type}. Available types: {available_types}")
        
        engine_class = cls._engine_types[engine_type]
        return engine_class(**kwargs)
    
    @classmethod
    def register_engine(cls, name: str, engine_class: type, display_name: str | None = None):
        """
        Register a new engine type manually.
        
        Args:
            name: Name of the engine type
            engine_class: Class implementing BaseInferenceEngine
            display_name: Optional user-friendly display name
        """
        if not issubclass(engine_class, BaseInferenceEngine):
            logger.warning(f"Engine class {engine_class} does not inherit from BaseInferenceEngine")
        
        if name in cls._engine_types:
            logger.warning(f"Engine type '{name}' already registered, replacing with new class.")  

        cls._engine_types[name] = engine_class
        
        # Set display name (priority: provided name > engine class display_name > fallback)
        if display_name:
            cls._engine_display_names[name] = display_name
        elif hasattr(engine_class, 'display_name'):
            cls._engine_display_names[name] = engine_class.display_name
        elif name not in cls._engine_display_names:
            cls._engine_display_names[name] = name.replace('_', ' ').title()
            
        logger.info(f"Manually registered engine type: {name} ({cls._engine_display_names[name]})")
    
    @classmethod
    def get_available_types(cls) -> list:
        """Get list of available engine types."""
        cls._discover_engines()  # Ensure engines are discovered
        return list(cls._engine_types.keys())
    
    @classmethod
    def get_display_name(cls, engine_type: str) -> str:
        """
        Get the user-friendly display name for an engine type.
        
        Args:
            engine_type: The engine type key
            
        Returns:
            str: User-friendly display name
        """
        cls._initialize_display_names()
        
        # First check if we have a custom display name in our mapping
        if engine_type in cls._engine_display_names:
            return cls._engine_display_names[engine_type]
        
        # If engine class exists, try to get display name from the engine class itself
        if engine_type in cls._engine_types:
            engine_class = cls._engine_types[engine_type]
            if hasattr(engine_class, 'display_name'):
                return engine_class.display_name
        
        # Fallback to formatted engine type
        return engine_type.replace('_', ' ').title()
    
    @classmethod
    def get_available_engines_with_names(cls) -> dict:
        """
        Get a dictionary mapping engine types to their display names.
        
        Returns:
            dict: {engine_type: display_name}
        """
        cls._initialize_display_names()
        return {
            engine_type: cls.get_display_name(engine_type) 
            for engine_type in cls._engine_types.keys()
        }

    @classmethod
    def get_available_engines_with_metadata(cls) -> list:
        """
        Get a list of available inference engines with detailed metadata.
        
        Returns:
            list: List of dictionaries containing engine metadata
        """
        cls._discover_engines()  # Ensure engines are discovered
        
        available_engines = []
        
        # Define metadata for each engine type
        engine_metadata = {
            'ultralytics': {
                'icon': 'fas fa-robot',
                'description': 'YOLO object detection and segmentation models',
                'primary': True,
                'dependencies': ['ultralytics', 'torch', 'torchvision']
            },
            'geti': {
                'icon': 'fas fa-microchip', 
                'description': 'Geti computer vision platform',
                'primary': True,
                'dependencies': ['geti-sdk']
            },
            'pass': {
                'icon': 'fas fa-forward',
                'description': 'Pass-through engine for testing',
                'primary': False,
                'dependencies': []
            }
        }
        
        for engine_type in cls._engine_types.keys():
            engine_class = cls._engine_types[engine_type]
            
            # Get basic metadata
            metadata = engine_metadata.get(engine_type, {
                'icon': 'fas fa-cog',
                'description': f'{cls.get_display_name(engine_type)} inference engine',
                'primary': False,
                'dependencies': []
            })
            
            # Check availability by testing dependencies
            available = True
            error_message = None
            
            try:
                # Try to instantiate the engine to check if dependencies are available
                test_engine = engine_class()
                if hasattr(test_engine, 'check_dependencies'):
                    available = test_engine.check_dependencies()
                    if not available:
                        error_message = "Dependencies not available"
            except ImportError as e:
                available = False
                error_message = f"Missing dependencies: {str(e)}"
            except Exception as e:
                available = False
                error_message = f"Engine not available: {str(e)}"
            
            engine_info = {
                'type': engine_type,
                'name': cls.get_display_name(engine_type),
                'icon': metadata['icon'],
                'description': metadata['description'],
                'available': available,
                'primary': metadata.get('primary', False),
                'dependencies': metadata.get('dependencies', [])
            }
            
            if not available and error_message:
                engine_info['error'] = error_message
                
            available_engines.append(engine_info)
        
        # Sort: primary engines first, then by name
        available_engines.sort(key=lambda x: (not x['primary'], x['name']))
        
        return available_engines

    @classmethod
    def unregister_engine(cls, engine_type: str):
        """Unregister an engine type (convenience function)"""
        if engine_type not in cls._engine_types:
            raise ValueError(f"Engine type '{engine_type}' is not registered")
        del cls._engine_types[engine_type]
        
        # Also remove from display names if present
        if engine_type in cls._engine_display_names:
            del cls._engine_display_names[engine_type]
            
        logger.info(f"Unregistered engine type: {engine_type}")
    
    @classmethod
    def rediscover_engines(cls):
        """Force re-discovery of engines (useful for development)"""
        cls._discovery_complete = False
        cls._engine_types.clear()
        cls._engine_display_names.clear()
        cls._discover_engines()
        logger.info("Forced engine re-discovery completed")
    
    @classmethod
    def get_discovery_info(cls) -> dict:
        """Get information about the discovery process"""
        cls._discover_engines()  # Ensure discovery is complete
        return {
            "discovery_complete": cls._discovery_complete,
            "engines_found": len(cls._engine_types),
            "engine_types": list(cls._engine_types.keys()),
            "engines_with_display_names": cls._engine_display_names.copy()
        }



if __name__ == "__main__":
    # Test the factory function
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    logger.info("Testing InferenceEngine factory with auto-discovery...")
    
    # Test discovery info
    discovery_info = InferenceEngineFactory.get_discovery_info()
    logger.info(f"Discovery info: {discovery_info}")
    
    # Test listing engines
    logger.info(f"Available engines: {InferenceEngineFactory.get_available_types()}")
    logger.info(f"Engine display names: {InferenceEngineFactory.get_available_engines_with_names()}")
    
    # Test individual display names
    for engine_type in InferenceEngineFactory.get_available_types():
        display_name = InferenceEngineFactory.get_display_name(engine_type)
        logger.info(f"  {engine_type} -> {display_name}")
    
    # Test all discovered engines
    for engine_type in InferenceEngineFactory.get_available_types():
        try:
            engine = InferenceEngineFactory.create(engine_type)
            logger.info(f"✓ Successfully created {engine_type} engine: {type(engine)}")
            
            # Test that it's properly instantiated
            info = engine.get_info()
            logger.info(f"  Engine info: {info}")
            
        except Exception as e:
            logger.error(f"✗ Failed to create {engine_type} engine: {e}")
    
    # Test runtime registration with a mock engine
    class MockEngine(BaseInferenceEngine):
        """Mock engine for testing registration"""
        display_name = "Mock Test Engine"
        
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.name = "MockEngine"
        
        def _load_model(self, model_file: str, device: str) -> bool:
            return True
        
        def check_valid_model(self, model_file: str) -> bool:
            return True
        
        def _preprocess(self, image):
            return image
        
        def _infer(self, preprocessed_input):
            return {"mock": "result"}
        
        def _postprocess(self, raw_output):
            return raw_output
        
        def draw(self, image, results):
            return image
        
        def result_to_json(self, results, output_format: str = "dict") -> str:
            if output_format == "dict":
                return json.dumps(results)
            return '{"mock": "result"}'
    
    try:
        # Test manual registration with display name
        InferenceEngineFactory.register_engine('mock', MockEngine, 'Override Mock Engine')
        logger.info("✓ Successfully registered mock engine with custom display name")
        
        # Test display name
        display_name = InferenceEngineFactory.get_display_name('mock')
        logger.info(f"  Mock engine display name: {display_name}")
        
        # Test creation of registered engine
        mock_engine = InferenceEngineFactory.create('mock')
        logger.info(f"✓ Successfully created mock engine: {type(mock_engine)}")
        logger.info(f"  Mock engine info: {mock_engine.get_info()}")
        
        # Test updated engine list
        logger.info(f"Updated available engines: {InferenceEngineFactory.get_available_types()}")
        
        # Test unregistration
        InferenceEngineFactory.unregister_engine('mock')
        logger.info("✓ Successfully unregistered mock engine")
        logger.info(f"Final available engines: {InferenceEngineFactory.get_available_types()}")
        
    except Exception as e:
        logger.error(f"✗ Failed runtime registration test: {e}")
    
    # Test invalid engine type
    try:
        engine = InferenceEngineFactory.create('invalid_engine')
        logger.error("✗ Should have raised ValueError for invalid engine")
    except ValueError as e:
        logger.info(f"✓ Correctly raised ValueError for invalid engine: {e}")
    except Exception as e:
        logger.error(f"✗ Unexpected error for invalid engine: {e}")
    
    # Test rediscovery
    try:
        logger.info("Testing rediscovery...")
        initial_count = len(InferenceEngineFactory.get_available_types())
        InferenceEngineFactory.rediscover_engines()
        final_count = len(InferenceEngineFactory.get_available_types())
        logger.info(f"✓ Rediscovery completed: {initial_count} -> {final_count} engines")
        
    except Exception as e:
        logger.error(f"✗ Rediscovery test failed: {e}")
    
    # Test class name to key conversion
    test_names = [
        "UltralyticsEngine",
        "GetiEngine", 
        "CustomObjectDetectionEngine",
        "MyAIEngine",
        "SimpleEngine",
        "AdvancedInferenceEngine"
    ]
    
    logger.info("Testing class name to key conversion:")
    for name in test_names:
        key = InferenceEngineFactory._class_name_to_key(name)
        logger.info(f"  {name} -> {key}")
    
    logger.info("Factory testing completed!")
