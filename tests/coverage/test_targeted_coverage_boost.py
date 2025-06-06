"""
Targeted Coverage Boost Tests

This file contains tests specifically targeting uncovered lines in the codebase.
"""

import importlib.util
import sys
import unittest
from unittest.mock import patch

# Optional dependency imports
try:
    HAS_PANDAS = importlib.util.find_spec("pandas") is not None
except ImportError:
    HAS_PANDAS = False

from datason.core import serialize


class TestSpecificUncoveredLines(unittest.TestCase):
    """Target the exact lines that need coverage."""

    def test_core_lines_14_15_ml_import_failure(self):
        """Test core.py lines 14-15: ML serializers import failure."""
        # Force import error by temporarily modifying sys.modules
        original_modules = sys.modules.copy()

        try:
            # Remove the module if it exists
            if "datason.ml_serializers" in sys.modules:
                del sys.modules["datason.ml_serializers"]

            # Create a module that will raise ImportError
            class FailingModule:
                def __getattr__(self, name):
                    if name == "detect_and_serialize_ml_object":
                        raise ImportError("Module not found")
                    raise AttributeError(name)

            sys.modules["datason.ml_serializers"] = FailingModule()

            # Reload core module to trigger import failure path
            if "datason.core" in sys.modules:
                del sys.modules["datason.core"]

            # Import should work despite ML serializer failure
            from datason.core import serialize as test_serialize

            # Test that basic serialization still works
            result = test_serialize({"test": "value"})
            self.assertEqual(result, {"test": "value"})

        finally:
            # Restore original modules
            sys.modules.clear()
            sys.modules.update(original_modules)

    def test_core_lines_19_20_ml_function_none(self):
        """Test core.py lines 19-20: When detect_and_serialize_ml_object is None."""
        from datason.core import serialize

        # Patch the function to be None (import fallback scenario)
        with patch("datason.core.detect_and_serialize_ml_object", None):
            # Create custom object that would normally be handled by ML serializer
            class CustomObject:
                def __init__(self):
                    self.data = "test"

            obj = CustomObject()
            result = serialize(obj)

            # Should fall back to dict serialization
            self.assertEqual(result, {"data": "test"})

    def test_core_line_93_dict_method_exception(self):
        """Test core.py line 93: Exception in dict() method."""

        # Create object with failing dict() method
        class BadDictMethod:
            def dict(self):
                raise RuntimeError("dict() failed")

            def __init__(self):
                self.fallback = "works"

        obj = BadDictMethod()
        result = serialize(obj)

        # Should fall back to __dict__
        self.assertEqual(result, {"fallback": "works"})

    def test_core_line_100_no_dict_attribute(self):
        """Test core.py line 100: Object without __dict__."""
        # Basic object() has no __dict__
        obj = object()
        result = serialize(obj)

        # Should fall back to string representation
        self.assertIsInstance(result, str)
        self.assertIn("object", result)

    def test_core_lines_106_108_vars_exception(self):
        """Test core.py lines 106-108: Exception in vars() or dict access."""

        # Create object that causes issues with dict access
        class ProblematicObject:
            def __getattribute__(self, name):
                if name == "__dict__":
                    # First call returns descriptor, second call fails
                    if not hasattr(self.__class__, "_called"):
                        self.__class__._called = True
                        return {}  # Empty dict to trigger line 133
                    raise AttributeError("No __dict__")
                return super().__getattribute__(name)

        obj = ProblematicObject()
        result = serialize(obj)

        # Should handle gracefully
        self.assertIsInstance(result, str)

    def test_core_line_133_empty_dict_fallback(self):
        """Test line 133 in core.py - empty dict fallback behavior."""

        class EmptyDictObject:
            pass

        obj = EmptyDictObject()
        result = serialize(obj)

        # With new type handler system, empty __dict__ returns empty dict
        self.assertEqual(result, {})


class TestDateTimeUtilsUncoveredLines(unittest.TestCase):
    """Target datetime_utils uncovered lines."""

    def test_datetime_lines_14_15_pandas_import_fail(self):
        """Test datetime_utils.py lines 14-15: Pandas import failure."""
        from datason.datetime_utils import ensure_timestamp

        with patch("datason.datetime_utils.pd", None):
            with self.assertRaises(ImportError) as context:
                ensure_timestamp("2023-01-01")

            self.assertIn("pandas is required", str(context.exception))

    def test_datetime_lines_156_159_column_iteration(self):
        """Test datetime_utils.py lines 156-159: DataFrame column iteration."""
        # Test is already covered but we need specific edge case
        try:
            import pandas as pd

            # Create DataFrame with date column
            df = pd.DataFrame({"date": ["2023-01-01", "2023-01-02"], "value": [1, 2]})

            from datason.datetime_utils import ensure_dates

            result = ensure_dates(df)

            # Should process successfully
            self.assertIsInstance(result, pd.DataFrame)

        except ImportError:
            self.skipTest("pandas not available")

    def test_datetime_lines_183_189_190_type_validation(self):
        """Test datetime_utils.py lines 183, 189-190: Type validation."""
        from datason.datetime_utils import ensure_dates

        # Test different invalid input types
        with self.assertRaises(TypeError):
            ensure_dates("string")

        with self.assertRaises(TypeError):
            ensure_dates(123)

        with self.assertRaises(TypeError):
            ensure_dates([1, 2, 3])

    def test_datetime_lines_194_196_pandas_none_fallback(self):
        """Test datetime_utils.py lines 194-196: pandas None fallback."""
        from datason.datetime_utils import convert_pandas_timestamps

        with patch("datason.datetime_utils.pd", None):
            # Should return unchanged when pandas is None
            test_data = {"date": "2023-01-01", "value": 42}
            result = convert_pandas_timestamps(test_data)
            self.assertEqual(result, test_data)


class TestMLSerializersUncoveredLines(unittest.TestCase):
    """Target ML serializers uncovered lines."""

    def test_ml_lines_14_49_import_fallbacks(self):
        """Test ml_serializers.py lines 14-49: Import fallback paths."""
        from datason.ml_serializers import (
            serialize_huggingface_tokenizer,
            serialize_jax_array,
            serialize_pil_image,
            serialize_pytorch_tensor,
            serialize_scipy_sparse,
            serialize_sklearn_model,
            serialize_tensorflow_tensor,
        )

        # Test each serializer when its library is None
        with patch("datason.ml_serializers.torch", None):
            result = serialize_pytorch_tensor("test")
            self.assertEqual(result["__datason_type__"], "torch.Tensor")
            self.assertEqual(result["__datason_value__"], "test")

        with patch("datason.ml_serializers.tf", None):
            result = serialize_tensorflow_tensor("test")
            self.assertEqual(result["__datason_type__"], "tf.Tensor")
            self.assertEqual(result["__datason_value__"], "test")

        with patch("datason.ml_serializers.sklearn", None):
            result = serialize_sklearn_model("test")
            self.assertEqual(result["__datason_type__"], "sklearn.model")
            self.assertEqual(result["__datason_value__"], "test")

        with patch("datason.ml_serializers.jax", None):
            result = serialize_jax_array("test")
            self.assertEqual(result["__datason_type__"], "jax.Array")
            self.assertEqual(result["__datason_value__"], "test")

        with patch("datason.ml_serializers.scipy", None):
            result = serialize_scipy_sparse("test")
            self.assertEqual(result["__datason_type__"], "scipy.sparse")
            self.assertEqual(result["__datason_value__"], "test")

        with patch("datason.ml_serializers.Image", None):
            result = serialize_pil_image("test")
            self.assertEqual(result["__datason_type__"], "PIL.Image")
            self.assertEqual(result["__datason_value__"], "test")

        with patch("datason.ml_serializers.transformers", None):
            result = serialize_huggingface_tokenizer("test")
            self.assertEqual(result["__datason_type__"], "transformers.tokenizer")
            self.assertEqual(result["__datason_value__"], "test")


if __name__ == "__main__":
    unittest.main()
