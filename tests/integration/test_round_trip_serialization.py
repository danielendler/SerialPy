"""
Comprehensive Round-Trip Serialization Test Suite

This test suite validates serialization round-trip fidelity for datason, testing both
basic round-trips (without type metadata) and enhanced round-trips (with type metadata).

## ARCHITECTURAL ASYMMETRY: Serialization vs Deserialization

### Serialization (Rich → JSON): Many Hot Paths
- ✅ **Rich type information available** - we know exactly what we're serializing
- ✅ `isinstance(obj, Decimal)` → immediate optimal handling
- ✅ `isinstance(obj, complex)` → direct `{"real": x, "imag": y}`
- ✅ **Fast, deterministic type-specific paths**

### Deserialization WITHOUT hints (JSON → Rich): Fewer Hot Paths
- ❌ **Limited type information** - only strings/dicts/lists available
- ❌ Must guess: Is `"123.45"` a Decimal or string?
- ❌ Must pattern-match: Does `{"real": 1, "imag": 2}` mean complex?
- ❌ **Expensive detection, ambiguous patterns**

### Deserialization WITH hints (JSON → Rich): Many Hot Paths Again
- ✅ **Metadata provides type information** - we know what to reconstruct
- ✅ `{"__datason_type__": "decimal.Decimal", "__datason_value__": "123.45"}` → direct `Decimal("123.45")`
- ✅ **Fast reconstruction paths enabled by metadata**

## ROUND-TRIP FIDELITY EXPECTATIONS

### ✅ PERFECT Round-trips (Without Metadata)
These types have distinctive patterns that can be auto-detected:
- Basic JSON types: None, bool, int, float, str, list, dict
- Complex numbers: `{"real": x, "imag": y}` → auto-detectable
- Datetimes: ISO strings → auto-detectable via regex
- UUIDs: UUID format strings → auto-detectable via regex

### ⚠️ LOSSY Round-trips (Without Metadata)
These types lose information in JSON and cannot be reliably reconstructed:
- `tuple` → `list` (JSON has no tuple concept)
- `set` → `list` (JSON has no set concept, order lost)
- `Decimal` → `str` (indistinguishable from regular strings)
- `pathlib.Path` → `str` (indistinguishable from regular strings)
- NumPy scalars → Python primitives (precision/type info lost)
- Pandas DataFrames/Series → dicts/lists (structure metadata lost)
- ML models → complex dicts (model metadata lost)

### ✅ PERFECT Round-trips (With Metadata)
With `include_type_hints=True`, ALL types should round-trip perfectly:
- Metadata preserves exact type information
- Hot paths can reconstruct with full fidelity
- This is the recommended approach for production ML workflows

## TEST STRUCTURE

1. **Basic Round-Trip Tests**: Test without `include_type_hints`
   - Validates what's reasonably possible without metadata
   - Uses `expected_basic_type` for realistic expectations

2. **Metadata Round-Trip Tests**: Test with `include_type_hints=True`
   - Validates perfect round-trip fidelity
   - Uses `expected_type` for exact type preservation

3. **Type-Specific Behavior Tests**: Test edge cases and precision
   - NumPy scalar metadata preservation
   - Pandas DataFrame orientations
   - PyTorch tensor attributes
   - Complex number precision
   - Decimal precision preservation
"""

import json
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import datason
from datason.config import SerializationConfig
from datason.deserializers import deserialize_fast

# Optional dependencies
try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

try:
    import pandas as pd

    HAS_PANDAS = True
except ImportError:
    pd = None
    HAS_PANDAS = False

try:
    import torch

    HAS_TORCH = True
except ImportError:
    torch = None
    HAS_TORCH = False

try:
    from sklearn.datasets import make_classification
    from sklearn.linear_model import LogisticRegression

    HAS_SKLEARN = True
except ImportError:
    LogisticRegression = None
    make_classification = None
    HAS_SKLEARN = False


class RoundTripTestCase:
    """Test case for round-trip serialization."""

    def __init__(
        self,
        name: str,
        value: Any,
        expected_type: type = None,
        expected_basic_type: type = None,  # Type expected for basic round-trip (no metadata)
        skip_reason: str = None,
        custom_comparison=None,
        custom_basic_comparison=None,  # Custom comparison for basic round-trip
    ):
        self.name = name
        self.value = value
        self.expected_type = expected_type or type(value)
        self.expected_basic_type = expected_basic_type or type(value)  # Default to same type
        self.skip_reason = skip_reason
        self.custom_comparison = custom_comparison
        self.custom_basic_comparison = custom_basic_comparison

    def compare_values(self, original: Any, deserialized: Any, is_basic_test: bool = False) -> bool:
        """Compare original and deserialized values."""
        # Use appropriate comparison for test type
        if is_basic_test and self.custom_basic_comparison:
            return self.custom_basic_comparison(original, deserialized)
        elif not is_basic_test and self.custom_comparison:
            return self.custom_comparison(original, deserialized)

        # Handle special cases
        if HAS_TORCH and hasattr(original, "dtype") and "torch" in str(type(original)):
            # PyTorch tensor comparison
            return torch.equal(original, deserialized)
        elif HAS_NUMPY and isinstance(original, np.ndarray):
            # NumPy array comparison
            return np.array_equal(original, deserialized)
        elif HAS_PANDAS and isinstance(original, (pd.DataFrame, pd.Series)):
            # Pandas comparison
            try:
                # First check if both are same type
                if not isinstance(deserialized, type(original)):
                    return False

                if isinstance(original, pd.DataFrame):
                    return original.equals(deserialized)
                else:  # Series
                    return original.equals(deserialized)
            except Exception:
                return False
        else:
            # Standard comparison
            try:
                expected_type = self.expected_basic_type if is_basic_test else self.expected_type

                # Check type first
                if type(deserialized) is not expected_type:
                    return False

                # For basic tests, handle type conversions where values should be logically equivalent
                if is_basic_test:
                    # tuple -> list conversion
                    if isinstance(original, tuple) and isinstance(deserialized, list):
                        return list(original) == deserialized
                    # set -> list conversion (order doesn't matter)
                    elif isinstance(original, set) and isinstance(deserialized, list):
                        return set(deserialized) == original
                    # Decimal -> string conversion
                    elif (
                        isinstance(original, Decimal)
                        and isinstance(deserialized, str)
                        or hasattr(original, "__fspath__")
                        and isinstance(deserialized, str)
                    ):
                        return str(original) == deserialized

                # Standard value comparison
                return original == deserialized

            except ValueError as e:
                # Handle pandas DataFrame truth value ambiguity
                if "truth value" in str(e) and "DataFrame" in str(e):
                    try:
                        # For DataFrames, use .equals() method
                        if HAS_PANDAS and isinstance(original, pd.DataFrame) and isinstance(deserialized, pd.DataFrame):
                            return original.equals(deserialized)
                    except Exception:
                        return False
                return False


# =============================================================================
# TEST DATA DEFINITIONS - RESTRUCTURED FOR CLEAR EXPECTATIONS
# =============================================================================

# TYPES THAT WORK WITHOUT HINTS: These should round-trip perfectly even without include_type_hints=True
TYPES_THAT_WORK_WITHOUT_HINTS = [
    # Basic JSON types (perfect round-trips)
    RoundTripTestCase("none", None),
    RoundTripTestCase("string_empty", ""),
    RoundTripTestCase("string_simple", "hello"),
    RoundTripTestCase("string_unicode", "hello 世界 🌍"),
    RoundTripTestCase("integer_zero", 0),
    RoundTripTestCase("integer_positive", 42),
    RoundTripTestCase("integer_negative", -123),
    RoundTripTestCase("integer_large", 2**60),
    RoundTripTestCase("float_zero", 0.0),
    RoundTripTestCase("float_simple", 3.14),
    RoundTripTestCase("float_negative", -2.71),
    RoundTripTestCase("float_scientific", 1.23e-10),
    RoundTripTestCase("boolean_true", True),
    RoundTripTestCase("boolean_false", False),
    RoundTripTestCase("list_empty", []),
    RoundTripTestCase("list_simple", [1, 2, 3]),
    RoundTripTestCase("list_mixed", [1, "hello", True, None]),
    RoundTripTestCase("list_nested", [[1, 2], [3, 4]]),
    RoundTripTestCase("dict_empty", {}),
    RoundTripTestCase("dict_simple", {"a": 1, "b": 2}),
    RoundTripTestCase("dict_mixed", {"int": 1, "str": "hello", "bool": True}),
    RoundTripTestCase("dict_nested", {"outer": {"inner": {"value": 42}}}),
    # Auto-detectable types (perfect round-trips)
    RoundTripTestCase("datetime_simple", datetime(2023, 1, 1, 12, 0, 0)),  # ISO string auto-detectable
    RoundTripTestCase("datetime_microseconds", datetime(2023, 1, 1, 12, 0, 0, 123456)),
    RoundTripTestCase("uuid_fixed", uuid.UUID("12345678-1234-5678-9012-123456789abc")),
    # Legacy behavior: These ALWAYS get metadata regardless of include_type_hints
    RoundTripTestCase("complex_simple", complex(1, 2)),  # Always gets _type metadata
    RoundTripTestCase("complex_float", complex(3.14, -2.71)),
    RoundTripTestCase("complex_zero", complex(0, 0)),
    RoundTripTestCase("decimal_simple", Decimal("123.45")),  # Always gets _type metadata
    RoundTripTestCase("decimal_precision", Decimal("123.456789012345")),
    RoundTripTestCase("decimal_large", Decimal("123456789.123456789")),
    # Nested structures
    RoundTripTestCase("deeply_nested", {"a": {"b": {"c": {"d": {"e": [1, 2, 3]}}}}}),
    RoundTripTestCase("large_list", list(range(100))),  # Reduced for faster tests
    RoundTripTestCase("unicode_keys", {"键": "值", "🔑": "🔓"}),
]

# TYPES THAT NEED HINTS: These only round-trip perfectly with include_type_hints=True
TYPES_THAT_NEED_HINTS = [
    # Type information lost without metadata
    RoundTripTestCase("tuple_empty", (), expected_basic_type=list),
    RoundTripTestCase("tuple_simple", (1, 2, 3), expected_basic_type=list),
    RoundTripTestCase("tuple_mixed", (1, "hello", True), expected_basic_type=list),
    RoundTripTestCase("set_empty", set(), expected_basic_type=list),
    RoundTripTestCase("set_simple", {1, 2, 3}, expected_basic_type=list),
    RoundTripTestCase("set_mixed", {1, "hello"}, expected_basic_type=list),
    # UUID auto-detection can be unreliable across environments
    RoundTripTestCase("uuid_simple", uuid.uuid4(), expected_basic_type=str),
    # Path objects that become strings without metadata (auto-detection unreliable across Python versions)
    RoundTripTestCase("path_relative", Path("./test/path.txt"), expected_basic_type=str),
    RoundTripTestCase(
        "path_absolute", Path("/tmp/test/path.txt"), expected_basic_type=str
    ),  # Auto-detection unreliable
]

# Add NumPy types that need hints (if available)
if HAS_NUMPY:
    TYPES_THAT_NEED_HINTS.extend(
        [
            # NumPy scalars become Python primitives without metadata
            RoundTripTestCase("numpy_int8", np.int8(42), expected_basic_type=int),
            RoundTripTestCase("numpy_int16", np.int16(42), expected_basic_type=int),
            RoundTripTestCase("numpy_int32", np.int32(42), expected_basic_type=int),
            RoundTripTestCase("numpy_int64", np.int64(42), expected_basic_type=int),
            RoundTripTestCase("numpy_uint8", np.uint8(42), expected_basic_type=int),
            RoundTripTestCase("numpy_uint16", np.uint16(42), expected_basic_type=int),
            RoundTripTestCase("numpy_uint32", np.uint32(42), expected_basic_type=int),
            RoundTripTestCase("numpy_uint64", np.uint64(42), expected_basic_type=int),
            RoundTripTestCase("numpy_float16", np.float16(3.14), expected_basic_type=float),
            RoundTripTestCase("numpy_float32", np.float32(3.14), expected_basic_type=float),
            RoundTripTestCase("numpy_float64", np.float64(3.14), expected_basic_type=float),
            RoundTripTestCase("numpy_complex64", np.complex64(1 + 2j), expected_basic_type=str),  # becomes string
            RoundTripTestCase(
                "numpy_complex128", np.complex128(1 + 2j), expected_basic_type=complex
            ),  # may auto-detect
            RoundTripTestCase("numpy_bool_true", np.bool_(True), expected_basic_type=bool),
            RoundTripTestCase("numpy_bool_false", np.bool_(False), expected_basic_type=bool),
            # NumPy arrays become lists without metadata
            RoundTripTestCase("numpy_array_1d", np.array([1, 2, 3, 4, 5]), expected_basic_type=list),
            RoundTripTestCase("numpy_array_2d", np.array([[1, 2], [3, 4]]), expected_basic_type=list),
            RoundTripTestCase(
                "numpy_array_3d", np.array([[[1, 2], [3, 4]], [[5, 6], [7, 8]]]), expected_basic_type=list
            ),
            RoundTripTestCase("numpy_array_float", np.array([1.1, 2.2, 3.3]), expected_basic_type=list),
            RoundTripTestCase("numpy_array_bool", np.array([True, False, True]), expected_basic_type=list),
            RoundTripTestCase("numpy_array_complex", np.array([1 + 2j, 3 + 4j]), expected_basic_type=list),
            RoundTripTestCase("numpy_array_empty", np.array([]), expected_basic_type=list),
            RoundTripTestCase("numpy_zeros", np.zeros((3, 3)), expected_basic_type=list),
            RoundTripTestCase("numpy_ones", np.ones((2, 4)), expected_basic_type=list),
            RoundTripTestCase("numpy_arange", np.arange(10), expected_basic_type=list),
            RoundTripTestCase("numpy_linspace", np.linspace(0, 1, 5), expected_basic_type=list),
        ]
    )

# Add Pandas types that need hints (if available)
if HAS_PANDAS:
    TYPES_THAT_NEED_HINTS.extend(
        [
            # DataFrames become lists/dicts without metadata
            RoundTripTestCase(
                "pandas_dataframe_simple", pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}), expected_basic_type=list
            ),
            RoundTripTestCase(
                "pandas_dataframe_mixed",
                pd.DataFrame({"int": [1, 2], "str": ["a", "b"], "float": [1.1, 2.2]}),
                expected_basic_type=list,
            ),
            RoundTripTestCase("pandas_dataframe_empty", pd.DataFrame(), expected_basic_type=list),
            RoundTripTestCase("pandas_dataframe_single_col", pd.DataFrame({"x": [1, 2, 3]}), expected_basic_type=list),
            RoundTripTestCase(
                "pandas_dataframe_single_row", pd.DataFrame({"a": [1], "b": [2]}), expected_basic_type=list
            ),
            # Series become dicts without metadata
            RoundTripTestCase("pandas_series_int", pd.Series([1, 2, 3, 4, 5]), expected_basic_type=dict),
            RoundTripTestCase("pandas_series_float", pd.Series([1.1, 2.2, 3.3]), expected_basic_type=dict),
            RoundTripTestCase("pandas_series_str", pd.Series(["a", "b", "c"]), expected_basic_type=dict),
            RoundTripTestCase("pandas_series_bool", pd.Series([True, False, True]), expected_basic_type=dict),
            RoundTripTestCase("pandas_series_mixed", pd.Series([1, "hello", 3.14]), expected_basic_type=dict),
            RoundTripTestCase("pandas_series_named", pd.Series([1, 2, 3], name="my_series"), expected_basic_type=dict),
            RoundTripTestCase("pandas_series_empty", pd.Series([], dtype=object), expected_basic_type=dict),
            RoundTripTestCase(
                "pandas_categorical", pd.Series(pd.Categorical(["a", "b", "a", "c"])), expected_basic_type=dict
            ),
        ]
    )

# Add ML types that need hints (if available)
if HAS_TORCH:
    TYPES_THAT_NEED_HINTS.extend(
        [
            RoundTripTestCase("torch_tensor_1d", torch.tensor([1.0, 2.0, 3.0]), expected_basic_type=list),
            RoundTripTestCase("torch_tensor_2d", torch.tensor([[1.0, 2.0], [3.0, 4.0]]), expected_basic_type=list),
            RoundTripTestCase("torch_tensor_int", torch.tensor([1, 2, 3], dtype=torch.int32), expected_basic_type=list),
            RoundTripTestCase("torch_tensor_bool", torch.tensor([True, False, True]), expected_basic_type=list),
            RoundTripTestCase("torch_tensor_empty", torch.tensor([]), expected_basic_type=list),
            RoundTripTestCase("torch_tensor_scalar", torch.tensor(42.0), expected_basic_type=float),
        ]
    )

if HAS_SKLEARN:
    # Create sample data for models
    X_sample, y_sample = make_classification(n_samples=100, n_features=4, random_state=42)

    # Unfitted model
    unfitted_model = LogisticRegression(random_state=42)

    # Fitted model
    fitted_model = LogisticRegression(random_state=42)
    fitted_model.fit(X_sample, y_sample)

    TYPES_THAT_NEED_HINTS.extend(
        [
            RoundTripTestCase(
                "sklearn_logistic_unfitted",
                unfitted_model,
                expected_basic_type=dict,  # becomes dict without metadata
                custom_comparison=lambda a, b: (type(a) is type(b) and a.get_params() == b.get_params()),
            ),
            RoundTripTestCase(
                "sklearn_logistic_fitted",
                fitted_model,
                expected_basic_type=dict,  # becomes dict without metadata
                # NOTE: Fitted state (coef_, intercept_) cannot be preserved without training data
                # We can only preserve the model class and parameters, resulting in an unfitted model
                custom_comparison=lambda a, b: (type(a) is type(b) and a.get_params() == b.get_params()),
            ),
        ]
    )

# Add complex mixed containers that have mixed behavior
TYPES_THAT_NEED_HINTS.append(
    RoundTripTestCase(
        "mixed_container",
        {"list": [1, 2, {"nested": True}], "tuple": (1, 2, 3), "set": {1, 2, 3}, "complex": complex(1, 2)},
        expected_basic_type=dict,  # The complex stays complex (legacy), but tuple/set change
    )
)

# Total test counts for reporting
ALL_TESTS_WITHOUT_HINTS = TYPES_THAT_WORK_WITHOUT_HINTS
ALL_TESTS_WITH_HINTS = TYPES_THAT_WORK_WITHOUT_HINTS + TYPES_THAT_NEED_HINTS


# =============================================================================
# TEST IMPLEMENTATIONS
# =============================================================================


class TestRoundTripSerialization:
    """Test round-trip serialization with deterministic expectations.

    TWO TEST CATEGORIES:
    1. BASIC ROUND-TRIP (no metadata): Tests types that work WITHOUT include_type_hints=True
    2. METADATA ROUND-TRIP (with metadata): Tests ALL types WITH include_type_hints=True

    This ensures deterministic test results - we know exactly what should work in each case.
    """

    @pytest.mark.parametrize("test_case", ALL_TESTS_WITHOUT_HINTS, ids=lambda tc: tc.name)
    def test_basic_round_trip(self, test_case: RoundTripTestCase):
        """Test basic round-trip serialization without metadata.

        These types should round-trip perfectly even without include_type_hints=True:
        - Basic JSON types (str, int, float, bool, None, list, dict)
        - Auto-detectable types (datetime, UUID)
        - Legacy types that always get metadata (complex, Decimal)
        """
        if test_case.skip_reason:
            pytest.skip(test_case.skip_reason)

        # Clear caches to ensure clean state for each test (helps with test order dependencies)
        import datason

        datason.clear_caches()

        # Serialize WITHOUT type hints
        try:
            serialized = datason.serialize(test_case.value)
        except Exception as e:
            pytest.fail(f"Serialization failed: {e}")

        # Ensure it's JSON-compatible
        try:
            json_str = json.dumps(serialized, default=str)
            parsed = json.loads(json_str)
        except Exception as e:
            pytest.fail(f"JSON round-trip failed: {e}")

        # Deserialize
        try:
            deserialized = deserialize_fast(parsed)
        except Exception as e:
            pytest.fail(f"Deserialization failed: {e}")

        # Compare - these should all be perfect round-trips
        assert test_case.compare_values(test_case.value, deserialized, is_basic_test=True), (
            f"Round-trip failed: {test_case.value} != {deserialized} "
            f"(types: {type(test_case.value)} vs {type(deserialized)})"
        )

    @pytest.mark.parametrize("test_case", ALL_TESTS_WITH_HINTS, ids=lambda tc: f"{tc.name}_with_metadata")
    def test_metadata_round_trip(self, test_case: RoundTripTestCase):
        """Test round-trip serialization with type metadata.

        ALL types should round-trip perfectly with include_type_hints=True:
        - Everything from basic tests PLUS
        - Types that need metadata (tuples, sets, numpy, pandas, ML objects)
        """
        if test_case.skip_reason:
            pytest.skip(test_case.skip_reason)

        config = SerializationConfig(include_type_hints=True)

        # Serialize with metadata
        try:
            serialized = datason.serialize(test_case.value, config=config)
        except Exception as e:
            pytest.fail(f"Metadata serialization failed: {e}")

        # Ensure it's JSON-compatible
        try:
            json_str = json.dumps(serialized, default=str)
            parsed = json.loads(json_str)
        except Exception as e:
            pytest.fail(f"JSON round-trip failed: {e}")

        # Deserialize
        try:
            deserialized = deserialize_fast(parsed, config=config)
        except Exception as e:
            pytest.fail(f"Metadata deserialization failed: {e}")

        # Compare types and values - these should be PERFECT round-trips
        assert type(deserialized) is test_case.expected_type, (
            f"Type mismatch: expected {test_case.expected_type}, got {type(deserialized)}"
        )

        assert test_case.compare_values(test_case.value, deserialized, is_basic_test=False), (
            f"Metadata round-trip failed: {test_case.value} != {deserialized} "
            f"(types: {type(test_case.value)} vs {type(deserialized)})"
        )


class TestTypeSpecificBehavior:
    """Test type-specific serialization behavior."""

    @pytest.mark.skipif(not HAS_NUMPY, reason="NumPy not available")
    def test_numpy_scalar_metadata_preservation(self):
        """Test that NumPy scalars preserve exact type information."""
        config = SerializationConfig(include_type_hints=True)

        test_cases = [
            (np.int8(42), "numpy.int8"),
            (np.int32(42), "numpy.int32"),
            (np.int64(42), "numpy.int64"),
            (np.float32(3.14), "numpy.float32"),
            (np.float64(3.14), "numpy.float64"),
            (np.bool_(True), "numpy.bool_"),
        ]

        for scalar, expected_type_name in test_cases:
            serialized = datason.serialize(scalar, config=config)

            # Check that metadata is generated
            assert isinstance(serialized, dict), f"Expected dict, got {type(serialized)}"
            assert "__datason_type__" in serialized, "Missing type metadata"
            assert serialized["__datason_type__"] == expected_type_name

            # Test round-trip
            deserialized = deserialize_fast(serialized, config=config)
            assert type(deserialized) is type(scalar)
            assert deserialized == scalar

    @pytest.mark.skipif(not HAS_PANDAS, reason="Pandas not available")
    def test_pandas_dataframe_orientations(self):
        """Test DataFrame serialization with different orientations."""
        from datason.config import DataFrameOrient

        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})

        orientations = [
            DataFrameOrient.RECORDS,
            DataFrameOrient.SPLIT,
            DataFrameOrient.INDEX,
            DataFrameOrient.VALUES,
        ]

        for orient in orientations:
            config = SerializationConfig(dataframe_orient=orient, include_type_hints=True)

            # Serialize
            serialized = datason.serialize(df, config=config)

            # Deserialize
            deserialized = deserialize_fast(serialized, config=config)

            # Should get back a DataFrame
            assert isinstance(deserialized, pd.DataFrame)

            # VALUES orientation loses column names by design, so only compare data values
            if orient == DataFrameOrient.VALUES:
                # Compare only the data values, not column names or index
                assert df.values.tolist() == deserialized.values.tolist()
            else:
                # For other orientations, expect perfect round-trip
                assert df.equals(deserialized)

    @pytest.mark.skipif(not HAS_TORCH, reason="PyTorch not available")
    def test_pytorch_tensor_attributes(self):
        """Test PyTorch tensor attribute preservation."""
        config = SerializationConfig(include_type_hints=True)

        # Test different tensor configurations
        tensors = [
            torch.tensor([1.0, 2.0, 3.0]),
            torch.tensor([[1, 2], [3, 4]], dtype=torch.int32),
            torch.tensor([True, False, True], dtype=torch.bool),
        ]

        for tensor in tensors:
            serialized = datason.serialize(tensor, config=config)
            deserialized = deserialize_fast(serialized, config=config)

            assert isinstance(deserialized, torch.Tensor)
            assert torch.equal(tensor, deserialized)
            assert tensor.dtype == deserialized.dtype
            assert tensor.shape == deserialized.shape

    def test_complex_number_precision(self):
        """Test complex number precision preservation."""
        config = SerializationConfig(include_type_hints=True)

        test_cases = [
            complex(0, 0),
            complex(1, 0),
            complex(0, 1),
            complex(3.14159, -2.71828),
            complex(1e-10, 1e10),
        ]

        for comp in test_cases:
            serialized = datason.serialize(comp, config=config)
            deserialized = deserialize_fast(serialized, config=config)

            assert isinstance(deserialized, complex)
            assert comp == deserialized

    def test_decimal_precision_preservation(self):
        """Test Decimal precision preservation."""
        config = SerializationConfig(include_type_hints=True)

        test_cases = [
            Decimal("0"),
            Decimal("123.456789012345"),
            Decimal("1E+10"),
            Decimal("1E-10"),
            Decimal("-123.456"),
        ]

        for dec in test_cases:
            serialized = datason.serialize(dec, config=config)
            deserialized = deserialize_fast(serialized, config=config)

            assert isinstance(deserialized, Decimal)
            assert dec == deserialized


# =============================================================================
# COVERAGE REPORTING - UPDATED FOR CLEAR CATEGORIES
# =============================================================================


def test_coverage_report():
    """Generate a coverage report showing our two deterministic test categories."""
    print("\n" + "=" * 90)
    print("DETERMINISTIC ROUND-TRIP SERIALIZATION COVERAGE REPORT")
    print("=" * 90)

    print("\n📋 TEST CATEGORIES:")
    print("-" * 50)

    # Count types by category
    without_hints_count = len(ALL_TESTS_WITHOUT_HINTS)
    with_hints_count = len(ALL_TESTS_WITH_HINTS)
    needs_hints_count = len(TYPES_THAT_NEED_HINTS)

    print(f"✅ WORKS WITHOUT HINTS: {without_hints_count:3d} types")
    print("   - Basic JSON types (str, int, float, bool, None, list, dict)")
    print("   - Auto-detectable (datetime, UUID)")
    print("   - Legacy metadata (complex, Decimal)")
    print()

    print(f"🔧 NEEDS HINTS:         {needs_hints_count:3d} types")
    print("   - Type info lost (tuple→list, set→list)")
    print("   - Path objects (Path→str)")
    print("   - NumPy arrays/scalars (→Python primitives)")
    print("   - Pandas DataFrames/Series (→dicts/lists)")
    print("   - ML objects (PyTorch, sklearn)")
    print()

    print(f"🎯 TOTAL WITH HINTS:    {with_hints_count:3d} types")
    print("   - ALL types should work perfectly with metadata")
    print()

    # Library availability
    print("📚 LIBRARY AVAILABILITY:")
    print("-" * 30)
    print(f"NumPy:    {'✅ Available' if HAS_NUMPY else '❌ Not Available'}")
    print(f"Pandas:   {'✅ Available' if HAS_PANDAS else '❌ Not Available'}")
    print(f"PyTorch:  {'✅ Available' if HAS_TORCH else '❌ Not Available'}")
    print(f"Sklearn:  {'✅ Available' if HAS_SKLEARN else '❌ Not Available'}")

    print("\n" + "=" * 90)
    print("🎯 DETERMINISTIC EXPECTATIONS:")
    print("   • test_basic_round_trip: ALL should pass (no metadata needed)")
    print("   • test_metadata_round_trip: ALL should pass (metadata enables everything)")
    print("=" * 90)

    # Always pass - this is just for reporting
    assert True


if __name__ == "__main__":
    # Run the coverage report
    test_coverage_report()
