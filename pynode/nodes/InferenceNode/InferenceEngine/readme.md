# InferenceEngine Factory - Runtime Registration

The InferenceEngine factory now supports runtime registration of custom engines, allowing you to add new inference engines without modifying the core factory code.

## Features

- **Runtime Registration**: Register new engines at runtime
- **Dynamic Engine Management**: List, register, and unregister engines
- **Backward Compatibility**: Existing factory function interface unchanged
- **Validation**: Basic validation of engine classes during registration

## Basic Usage

### Using Built-in Engines

```python
from InferenceEngine.inference_engine_factory import InferenceEngineFactory

# Create built-in engines
engine = InferenceEngineFactory('ultralytics')
geti_engine = InferenceEngineFactory('geti')
```

### Runtime Registration

```python
from InferenceEngine.inference_engine_factory import register_engine, InferenceEngineFactory, list_engines

# Define your custom engine
class MyCustomEngine:
    def __init__(self):
        self.model = None
    
    def get_info(self):
        return {"engine": "custom", "version": "1.0"}
    
    def load(self, model_path, device='cpu'):
        # Your model loading logic
        return True
    
    def infer(self, input_data):
        # Your inference logic
        return {"predictions": []}

# Register the engine
register_engine('my_custom', MyCustomEngine)

# Use the registered engine
engine = InferenceEngineFactory('my_custom')
```

## API Reference

### Functions

- `InferenceEngineFactory(engine_type: str)` - Create engine instance (backward compatible)
- `register_engine(engine_type: str, engine_class)` - Register new engine type
- `unregister_engine(engine_type: str)` - Remove engine type
- `list_engines()` - Get list of available engine types

### InferenceEngineRegistry Class

Direct access to the registry for advanced usage:

```python
from InferenceEngine.inference_engine_factory import _engine_registry

# Access registry directly
_engine_registry.register_engine('advanced', AdvancedEngine)
engine = _engine_registry.create_engine('advanced')
```

## Engine Requirements

Custom engines should implement these methods:

```python
class CustomEngine:
    def __init__(self):
        """Initialize the engine"""
        pass
    
    def get_info(self):
        """Return engine information dict"""
        return {"engine": "name", "version": "1.0"}
    
    def load(self, model_path, device='cpu'):
        """Load model, return True if successful"""
        return True
    
    def infer(self, input_data):
        """Run inference, return results dict"""
        return {"predictions": []}
```

## Example

See `example_custom_engine.py` for complete examples of:
- TensorFlow custom engine
- OpenVINO custom engine
- Registration and usage patterns

## Error Handling

- `ValueError` - Raised for invalid engine types or duplicate registrations
- Runtime validation ensures engine classes are callable
- Optional inheritance checking from BaseInferenceEngine (if available)
