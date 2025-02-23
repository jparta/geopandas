"""
Compatibility shim for the vectorized geometry operations.

Uses PyGEOS if available/set, otherwise loops through Shapely geometries.

"""
import warnings

import numpy as np
import pandas as pd

import shapely
import shapely.geometry
import shapely.geos
import shapely.ops
import shapely.wkb
import shapely.wkt
import shapely.validation

from shapely.geometry.base import BaseGeometry

from . import _compat as compat

try:
    import pygeos
except ImportError:
    geos = None


_names = {
    "MISSING": None,
    "NAG": None,
    "POINT": "Point",
    "LINESTRING": "LineString",
    "LINEARRING": "LinearRing",
    "POLYGON": "Polygon",
    "MULTIPOINT": "MultiPoint",
    "MULTILINESTRING": "MultiLineString",
    "MULTIPOLYGON": "MultiPolygon",
    "GEOMETRYCOLLECTION": "GeometryCollection",
}

if compat.USE_SHAPELY_20 or compat.USE_PYGEOS:
    if compat.USE_SHAPELY_20:
        type_mapping = {p.value: _names[p.name] for p in shapely.GeometryType}
    else:
        type_mapping = {p.value: _names[p.name] for p in pygeos.GeometryType}
    geometry_type_ids = list(type_mapping.keys())
    geometry_type_values = np.array(list(type_mapping.values()), dtype=object)
else:
    type_mapping, geometry_type_ids, geometry_type_values = None, None, None


def isna(value):
    """
    Check if scalar value is NA-like (None, np.nan or pd.NA).

    Custom version that only works for scalars (returning True or False),
    as `pd.isna` also works for array-like input returning a boolean array.
    """
    if value is None:
        return True
    elif isinstance(value, float) and np.isnan(value):
        return True
    elif value is pd.NA:
        return True
    else:
        return False


def _pygeos_to_shapely(geom):
    if geom is None:
        return None

    if compat.PYGEOS_SHAPELY_COMPAT:
        # we can only use this compatible fast path for shapely < 2, because
        # shapely 2+ doesn't expose clone
        if not compat.SHAPELY_GE_20:
            geom = shapely.geos.lgeos.GEOSGeom_clone(geom._ptr)
            return shapely.geometry.base.geom_factory(geom)

    # fallback going through WKB
    if pygeos.is_empty(geom) and pygeos.get_type_id(geom) == 0:
        # empty point does not roundtrip through WKB
        return shapely.wkt.loads("POINT EMPTY")
    elif pygeos.get_type_id(geom) == 2:
        # linearring does not roundtrip through WKB
        return shapely.LinearRing(shapely.wkb.loads(pygeos.to_wkb(geom)))
    else:
        return shapely.wkb.loads(pygeos.to_wkb(geom))


def _shapely_to_pygeos(geom):
    if geom is None:
        return None

    if compat.PYGEOS_SHAPELY_COMPAT:
        return pygeos.from_shapely(geom)

    # fallback going through WKB
    if geom.is_empty and geom.geom_type == "Point":
        # empty point does not roundtrip through WKB
        return pygeos.from_wkt("POINT EMPTY")
    else:
        return pygeos.from_wkb(geom.wkb)


def from_shapely(data):
    """
    Convert a list or array of shapely objects to an object-dtype numpy
    array of validated geometry elements.

    """
    # First try a fast path for pygeos if possible, but do this in a try-except
    # block because pygeos.from_shapely only handles Shapely objects, while
    # the rest of this function is more forgiving (also __geo_interface__).
    if compat.USE_PYGEOS and compat.PYGEOS_SHAPELY_COMPAT:
        if not isinstance(data, np.ndarray):
            arr = np.empty(len(data), dtype=object)
            with compat.ignore_shapely2_warnings():
                arr[:] = data
        else:
            arr = data
        try:
            return pygeos.from_shapely(arr)
        except TypeError:
            pass

    out = []

    for geom in data:
        if compat.USE_PYGEOS and isinstance(geom, pygeos.Geometry):
            out.append(geom)
        elif isinstance(geom, BaseGeometry):
            if compat.USE_PYGEOS:
                out.append(_shapely_to_pygeos(geom))
            else:
                out.append(geom)
        elif hasattr(geom, "__geo_interface__"):
            geom = shapely.geometry.shape(geom)
            if compat.USE_PYGEOS:
                out.append(_shapely_to_pygeos(geom))
            else:
                out.append(geom)
        elif isna(geom):
            out.append(None)
        else:
            raise TypeError("Input must be valid geometry objects: {0}".format(geom))

    if compat.USE_PYGEOS:
        return np.array(out, dtype=object)
    else:
        # numpy can expand geometry collections into 2D arrays, use this
        # two-step construction to avoid this
        aout = np.empty(len(data), dtype=object)
        with compat.ignore_shapely2_warnings():
            aout[:] = out
        return aout


def to_shapely(data):
    if compat.USE_PYGEOS:
        out = np.empty(len(data), dtype=object)
        with compat.ignore_shapely2_warnings():
            out[:] = [_pygeos_to_shapely(geom) for geom in data]
        return out
    else:
        return data


def from_wkb(data):
    """
    Convert a list or array of WKB objects to a np.ndarray[geoms].
    """
    if compat.USE_SHAPELY_20:
        return shapely.from_wkb(data)
    if compat.USE_PYGEOS:
        return pygeos.from_wkb(data)

    out = []

    for geom in data:
        if not isna(geom) and len(geom):
            geom = shapely.wkb.loads(geom, hex=isinstance(geom, str))
        else:
            geom = None
        out.append(geom)

    aout = np.empty(len(data), dtype=object)
    with compat.ignore_shapely2_warnings():
        aout[:] = out
    return aout


def to_wkb(data, hex=False, **kwargs):
    if compat.USE_SHAPELY_20:
        return shapely.to_wkb(data, hex=hex, **kwargs)
    elif compat.USE_PYGEOS:
        return pygeos.to_wkb(data, hex=hex, **kwargs)
    else:
        if hex:
            out = [geom.wkb_hex if geom is not None else None for geom in data]
        else:
            out = [geom.wkb if geom is not None else None for geom in data]
        return np.array(out, dtype=object)


def from_wkt(data):
    """
    Convert a list or array of WKT objects to a np.ndarray[geoms].
    """
    if compat.USE_SHAPELY_20:
        return shapely.from_wkt(data)
    if compat.USE_PYGEOS:
        return pygeos.from_wkt(data)

    out = []

    for geom in data:
        if not isna(geom) and len(geom):
            if isinstance(geom, bytes):
                geom = geom.decode("utf-8")
            geom = shapely.wkt.loads(geom)
        else:
            geom = None
        out.append(geom)

    aout = np.empty(len(data), dtype=object)
    with compat.ignore_shapely2_warnings():
        aout[:] = out
    return aout


def to_wkt(data, **kwargs):
    if compat.USE_SHAPELY_20:
        return shapely.to_wkt(data, **kwargs)
    elif compat.USE_PYGEOS:
        return pygeos.to_wkt(data, **kwargs)
    else:
        out = [geom.wkt if geom is not None else None for geom in data]
        return np.array(out, dtype=object)


def _points_from_xy(x, y, z=None):
    # helper method for shapely-based function
    if not len(x) == len(y):
        raise ValueError("x and y arrays must be equal length.")
    if z is not None:
        if not len(z) == len(x):
            raise ValueError("z array must be same length as x and y.")
        geom = [shapely.geometry.Point(i, j, k) for i, j, k in zip(x, y, z)]
    else:
        geom = [shapely.geometry.Point(i, j) for i, j in zip(x, y)]
    return geom


def points_from_xy(x, y, z=None):
    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    if z is not None:
        z = np.asarray(z, dtype="float64")

    if compat.USE_SHAPELY_20:
        return shapely.points(x, y, z)
    elif compat.USE_PYGEOS:
        return pygeos.points(x, y, z)
    else:
        out = _points_from_xy(x, y, z)
        aout = np.empty(len(x), dtype=object)
        with compat.ignore_shapely2_warnings():
            aout[:] = out
        return aout


# -----------------------------------------------------------------------------
# Helper methods for the vectorized operations
# -----------------------------------------------------------------------------


def _binary_method(op, left, right, **kwargs):
    # type: (str, np.array[geoms], [np.array[geoms]/BaseGeometry]) -> array-like
    if isinstance(right, BaseGeometry):
        right = from_shapely([right])[0]
    return getattr(pygeos, op)(left, right, **kwargs)


def _binary_geo(op, left, right):
    # type: (str, np.array[geoms], [np.array[geoms]/BaseGeometry]) -> np.array[geoms]
    """Apply geometry-valued operation

    Supports:

    -   difference
    -   symmetric_difference
    -   intersection
    -   union

    Parameters
    ----------
    op: string
    right: np.array[geoms] or single shapely BaseGeoemtry
    """
    if isinstance(right, BaseGeometry):
        # intersection can return empty GeometryCollections, and if the
        # result are only those, numpy will coerce it to empty 2D array
        data = np.empty(len(left), dtype=object)
        with compat.ignore_shapely2_warnings():
            data[:] = [
                getattr(s, op)(right) if s is not None and right is not None else None
                for s in left
            ]
        return data
    elif isinstance(right, np.ndarray):
        if len(left) != len(right):
            msg = "Lengths of inputs do not match. Left: {0}, Right: {1}".format(
                len(left), len(right)
            )
            raise ValueError(msg)
        data = np.empty(len(left), dtype=object)
        with compat.ignore_shapely2_warnings():
            data[:] = [
                getattr(this_elem, op)(other_elem)
                if this_elem is not None and other_elem is not None
                else None
                for this_elem, other_elem in zip(left, right)
            ]
        return data
    else:
        raise TypeError("Type not known: {0} vs {1}".format(type(left), type(right)))


def _binary_predicate(op, left, right, *args, **kwargs):
    # type: (str, np.array[geoms], np.array[geoms]/BaseGeometry, args/kwargs)
    #        -> array[bool]
    """Binary operation on np.array[geoms] that returns a boolean ndarray

    Supports:

    -  contains
    -  disjoint
    -  intersects
    -  touches
    -  crosses
    -  within
    -  overlaps
    -  covers
    -  covered_by
    -  equals

    Parameters
    ----------
    op: string
    right: np.array[geoms] or single shapely BaseGeoemtry
    """
    # empty geometries are handled by shapely (all give False except disjoint)
    if isinstance(right, BaseGeometry):
        data = [
            getattr(s, op)(right, *args, **kwargs) if s is not None else False
            for s in left
        ]
        return np.array(data, dtype=bool)
    elif isinstance(right, np.ndarray):
        data = [
            getattr(this_elem, op)(other_elem, *args, **kwargs)
            if not (this_elem is None or other_elem is None)
            else False
            for this_elem, other_elem in zip(left, right)
        ]
        return np.array(data, dtype=bool)
    else:
        raise TypeError("Type not known: {0} vs {1}".format(type(left), type(right)))


def _binary_op_float(op, left, right, *args, **kwargs):
    # type: (str, np.array[geoms], np.array[geoms]/BaseGeometry, args/kwargs)
    #        -> array
    """Binary operation on np.array[geoms] that returns a ndarray"""
    # used for distance -> check for empty as we want to return np.nan instead 0.0
    # as shapely does currently (https://github.com/Toblerity/Shapely/issues/498)
    if isinstance(right, BaseGeometry):
        data = [
            getattr(s, op)(right, *args, **kwargs)
            if not (s is None or s.is_empty or right.is_empty)
            else np.nan
            for s in left
        ]
        return np.array(data, dtype=float)
    elif isinstance(right, np.ndarray):
        if len(left) != len(right):
            msg = "Lengths of inputs do not match. Left: {0}, Right: {1}".format(
                len(left), len(right)
            )
            raise ValueError(msg)
        data = [
            getattr(this_elem, op)(other_elem, *args, **kwargs)
            if not (this_elem is None or this_elem.is_empty)
            | (other_elem is None or other_elem.is_empty)
            else np.nan
            for this_elem, other_elem in zip(left, right)
        ]
        return np.array(data, dtype=float)
    else:
        raise TypeError("Type not known: {0} vs {1}".format(type(left), type(right)))


def _binary_op(op, left, right, *args, **kwargs):
    # type: (str, np.array[geoms], np.array[geoms]/BaseGeometry, args/kwargs)
    #        -> array
    """Binary operation on np.array[geoms] that returns a ndarray"""
    # pass empty to shapely (relate handles this correctly, project only
    # for linestrings and points)
    if op == "project":
        null_value = np.nan
        dtype = float
    elif op == "relate":
        null_value = None
        dtype = object
    else:
        raise AssertionError("wrong op")

    if isinstance(right, BaseGeometry):
        data = [
            getattr(s, op)(right, *args, **kwargs) if s is not None else null_value
            for s in left
        ]
        return np.array(data, dtype=dtype)
    elif isinstance(right, np.ndarray):
        if len(left) != len(right):
            msg = "Lengths of inputs do not match. Left: {0}, Right: {1}".format(
                len(left), len(right)
            )
            raise ValueError(msg)
        data = [
            getattr(this_elem, op)(other_elem, *args, **kwargs)
            if not (this_elem is None or other_elem is None)
            else null_value
            for this_elem, other_elem in zip(left, right)
        ]
        return np.array(data, dtype=dtype)
    else:
        raise TypeError("Type not known: {0} vs {1}".format(type(left), type(right)))


def _affinity_method(op, left, *args, **kwargs):
    # type: (str, np.array[geoms], ...) -> np.array[geoms]

    # not all shapely.affinity methods can handle empty geometries:
    # affine_transform itself works (as well as translate), but rotate, scale
    # and skew fail (they try to unpack the bounds).
    # Here: consistently returning empty geom for input empty geom
    left = to_shapely(left)
    out = []
    for geom in left:
        if geom is None or geom.is_empty:
            res = geom
        else:
            res = getattr(shapely.affinity, op)(geom, *args, **kwargs)
        out.append(res)
    data = np.empty(len(left), dtype=object)
    with compat.ignore_shapely2_warnings():
        data[:] = out
    return from_shapely(data)


# -----------------------------------------------------------------------------
# Vectorized operations
# -----------------------------------------------------------------------------


#
# Unary operations that return non-geometry (bool or float)
#


def _unary_op(op, left, null_value=False):
    # type: (str, np.array[geoms], Any) -> np.array
    """Unary operation that returns a Series"""
    data = [getattr(geom, op, null_value) for geom in left]
    return np.array(data, dtype=np.dtype(type(null_value)))


def is_valid(data):
    if compat.USE_SHAPELY_20:
        return shapely.is_valid(data)
    elif compat.USE_PYGEOS:
        return pygeos.is_valid(data)
    else:
        return _unary_op("is_valid", data, null_value=False)


def is_empty(data):
    if compat.USE_SHAPELY_20:
        return shapely.is_empty(data)
    elif compat.USE_PYGEOS:
        return pygeos.is_empty(data)
    else:
        return _unary_op("is_empty", data, null_value=False)


def is_simple(data):
    if compat.USE_SHAPELY_20:
        return shapely.is_simple(data)
    elif compat.USE_PYGEOS:
        return pygeos.is_simple(data)
    else:
        return _unary_op("is_simple", data, null_value=False)


def is_ring(data):
    if "Polygon" in geom_type(data):
        warnings.warn(
            "is_ring currently returns True for Polygons, which is not correct. "
            "This will be corrected to False in a future release.",
            FutureWarning,
            stacklevel=3,
        )
    if compat.USE_PYGEOS:
        return pygeos.is_ring(data) | pygeos.is_ring(pygeos.get_exterior_ring(data))
    else:
        # for polygons operates on the exterior, so can't use _unary_op()
        results = []
        for geom in data:
            if geom is None:
                results.append(False)
            elif geom.geom_type == "Polygon":
                results.append(geom.exterior.is_ring)
            elif geom.geom_type in ["LineString", "LinearRing"]:
                results.append(geom.is_ring)
            else:
                results.append(False)
        return np.array(results, dtype=bool)


def is_closed(data):
    if compat.USE_SHAPELY_20:
        return shapely.is_closed(data)
    elif compat.USE_PYGEOS:
        return pygeos.is_closed(data)
    else:
        return _unary_op("is_closed", data, null_value=False)


def has_z(data):
    if compat.USE_SHAPELY_20:
        return shapely.has_z(data)
    elif compat.USE_PYGEOS:
        return pygeos.has_z(data)
    else:
        return _unary_op("has_z", data, null_value=False)


def geom_type(data):
    if compat.USE_SHAPELY_20:
        res = shapely.get_type_id(data)
        return geometry_type_values[np.searchsorted(geometry_type_ids, res)]
    elif compat.USE_PYGEOS:
        res = pygeos.get_type_id(data)
        return geometry_type_values[np.searchsorted(geometry_type_ids, res)]
    else:
        return _unary_op("geom_type", data, null_value=None)


def area(data):
    if compat.USE_SHAPELY_20:
        return shapely.area(data)
    elif compat.USE_PYGEOS:
        return pygeos.area(data)
    else:
        return _unary_op("area", data, null_value=np.nan)


def length(data):
    if compat.USE_SHAPELY_20:
        return shapely.length(data)
    elif compat.USE_PYGEOS:
        return pygeos.length(data)
    else:
        return _unary_op("length", data, null_value=np.nan)


#
# Unary operations that return new geometries
#


def _unary_geo(op, left, *args, **kwargs):
    # type: (str, np.array[geoms]) -> np.array[geoms]
    """Unary operation that returns new geometries"""
    # ensure 1D output, see note above
    data = np.empty(len(left), dtype=object)
    with compat.ignore_shapely2_warnings():
        data[:] = [getattr(geom, op, None) for geom in left]
    return data


def boundary(data):
    if compat.USE_SHAPELY_20:
        return shapely.boundary(data)
    elif compat.USE_PYGEOS:
        return pygeos.boundary(data)
    else:
        return _unary_geo("boundary", data)


def centroid(data):
    if compat.USE_SHAPELY_20:
        return shapely.centroid(data)
    elif compat.USE_PYGEOS:
        return pygeos.centroid(data)
    else:
        return _unary_geo("centroid", data)


def concave_hull(data, **kwargs):
    if compat.USE_SHAPELY_20:
        return shapely.concave_hull(data, **kwargs)
    if compat.USE_PYGEOS and compat.SHAPELY_GE_20:
        warnings.warn(
            "PyGEOS does not support concave_hull, and Shapely >= 2 is installed, "
            "thus using Shapely and not PyGEOS for calculating the concave_hull.",
            stacklevel=4,
        )
        return shapely.concave_hull(to_shapely(data), **kwargs)
    else:
        raise NotImplementedError(
            f"shapely >= 2.0 is required, "
            f"version {shapely.__version__} is installed"
        )


def convex_hull(data):
    if compat.USE_SHAPELY_20:
        return shapely.convex_hull(data)
    elif compat.USE_PYGEOS:
        return pygeos.convex_hull(data)
    else:
        return _unary_geo("convex_hull", data)


def delaunay_triangles(data, tolerance, only_edges):
    if compat.USE_SHAPELY_20:
        return shapely.delaunay_triangles(data, tolerance, only_edges)
    elif compat.USE_PYGEOS:
        return pygeos.delaunay_triangles(data, tolerance, only_edges)
    else:
        raise NotImplementedError(
            f"shapely >= 2.0 or PyGEOS is required, "
            f"version {shapely.__version__} is installed"
        )


def envelope(data):
    if compat.USE_SHAPELY_20:
        return shapely.envelope(data)
    elif compat.USE_PYGEOS:
        return pygeos.envelope(data)
    else:
        return _unary_geo("envelope", data)


def exterior(data):
    if compat.USE_SHAPELY_20:
        return shapely.get_exterior_ring(data)
    elif compat.USE_PYGEOS:
        return pygeos.get_exterior_ring(data)
    else:
        return _unary_geo("exterior", data)


def extract_unique_points(data):
    if compat.USE_SHAPELY_20:
        return shapely.extract_unique_points(data)
    elif compat.USE_PYGEOS:
        return pygeos.extract_unique_points(data)
    else:
        raise NotImplementedError(
            f"shapely >= 2.0 or PyGEOS is required, "
            f"version {shapely.__version__} is installed"
        )


def offset_curve(data, distance, quad_segs=8, join_style="round", mitre_limit=5.0):
    if compat.USE_SHAPELY_20:
        return shapely.offset_curve(
            data,
            distance=distance,
            quad_segs=quad_segs,
            join_style=join_style,
            mitre_limit=mitre_limit,
        )
    elif compat.USE_PYGEOS:
        return pygeos.offset_curve(data, distance, quad_segs, join_style, mitre_limit)
    else:
        raise NotImplementedError(
            f"shapely >= 2.0 or PyGEOS is required, "
            f"version {shapely.__version__} is installed"
        )


def interiors(data):
    data = to_shapely(data)
    has_non_poly = False
    inner_rings = []
    for geom in data:
        interior_ring_seq = getattr(geom, "interiors", None)
        # polygon case
        if interior_ring_seq is not None:
            inner_rings.append(list(interior_ring_seq))
        # non-polygon case
        else:
            has_non_poly = True
            inner_rings.append(None)
    if has_non_poly:
        warnings.warn(
            "Only Polygon objects have interior rings. For other "
            "geometry types, None is returned.",
            stacklevel=2,
        )
    data = np.empty(len(data), dtype=object)
    with compat.ignore_shapely2_warnings():
        data[:] = inner_rings
    return data


def representative_point(data):
    if compat.USE_PYGEOS:
        return pygeos.point_on_surface(data)
    else:
        # method and not a property -> can't use _unary_geo
        out = np.empty(len(data), dtype=object)
        with compat.ignore_shapely2_warnings():
            out[:] = [
                geom.representative_point() if geom is not None else None
                for geom in data
            ]
        return out


def minimum_bounding_circle(data):
    if compat.USE_SHAPELY_20:
        return shapely.minimum_bounding_circle(data)
    elif compat.USE_PYGEOS:
        return pygeos.minimum_bounding_circle(data)
    else:
        raise NotImplementedError(
            f"shapely >= 2.0 or PyGEOS is required, "
            f"version {shapely.__version__} is installed"
        )


def minimum_bounding_radius(data):
    if compat.USE_SHAPELY_20:
        return shapely.minimum_bounding_radius(data)
    elif compat.USE_PYGEOS:
        return pygeos.minimum_bounding_radius(data)
    else:
        raise NotImplementedError(
            f"shapely >= 2.0 or PyGEOS is required, "
            f"version {shapely.__version__} is installed"
        )


def segmentize(data, max_segment_length):
    if compat.USE_SHAPELY_20:
        return shapely.segmentize(data, max_segment_length)
    elif compat.USE_PYGEOS:
        return pygeos.segmentize(data, max_segment_length)
    else:
        raise NotImplementedError(
            "shapely >= 2.0 or PyGEOS is required, "
            f"version {shapely.__version__} is installed"
        )


#
# Binary predicates
#


def covers(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.covers(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("covers", data, other)
    else:
        return _binary_predicate("covers", data, other)


def covered_by(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.covered_by(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("covered_by", data, other)
    else:
        raise NotImplementedError(
            "covered_by is only implemented for pygeos, not shapely"
        )


def contains(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.contains(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("contains", data, other)
    else:
        return _binary_predicate("contains", data, other)


def crosses(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.crosses(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("crosses", data, other)
    else:
        return _binary_predicate("crosses", data, other)


def disjoint(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.disjoint(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("disjoint", data, other)
    else:
        return _binary_predicate("disjoint", data, other)


def equals(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.equals(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("equals", data, other)
    else:
        return _binary_predicate("equals", data, other)


def intersects(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.intersects(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("intersects", data, other)
    else:
        return _binary_predicate("intersects", data, other)


def overlaps(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.overlaps(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("overlaps", data, other)
    else:
        return _binary_predicate("overlaps", data, other)


def touches(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.touches(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("touches", data, other)
    else:
        return _binary_predicate("touches", data, other)


def within(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.within(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("within", data, other)
    else:
        return _binary_predicate("within", data, other)


def equals_exact(data, other, tolerance):
    if compat.USE_SHAPELY_20:
        return shapely.equals_exact(data, other, tolerance=tolerance)
    elif compat.USE_PYGEOS:
        return _binary_method("equals_exact", data, other, tolerance=tolerance)
    else:
        return _binary_predicate("equals_exact", data, other, tolerance=tolerance)


def almost_equals(self, other, decimal):
    if compat.USE_PYGEOS or compat.USE_SHAPELY_20:
        return self.equals_exact(other, 0.5 * 10 ** (-decimal))
    else:
        return _binary_predicate("almost_equals", self, other, decimal=decimal)


#
# Binary operations that return new geometries
#


def clip_by_rect(data, xmin, ymin, xmax, ymax):
    if compat.USE_PYGEOS:
        return pygeos.clip_by_rect(data, xmin, ymin, xmax, ymax)
    else:
        clipped_geometries = np.empty(len(data), dtype=object)
        with compat.ignore_shapely2_warnings():
            clipped_geometries[:] = [
                shapely.ops.clip_by_rect(s, xmin, ymin, xmax, ymax)
                if s is not None
                else None
                for s in data
            ]
        return clipped_geometries


def difference(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.difference(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("difference", data, other)
    else:
        return _binary_geo("difference", data, other)


def intersection(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.intersection(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("intersection", data, other)
    else:
        return _binary_geo("intersection", data, other)


def symmetric_difference(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.symmetric_difference(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("symmetric_difference", data, other)
    else:
        return _binary_geo("symmetric_difference", data, other)


def union(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.union(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("union", data, other)
    else:
        return _binary_geo("union", data, other)


#
# Other operations
#


def distance(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.distance(data, other)
    elif compat.USE_PYGEOS:
        return _binary_method("distance", data, other)
    else:
        return _binary_op_float("distance", data, other)


def hausdorff_distance(data, other, densify=None, **kwargs):
    if compat.USE_SHAPELY_20:
        return shapely.hausdorff_distance(data, other, densify=densify, **kwargs)
    elif compat.USE_PYGEOS:
        return _binary_method(
            "hausdorff_distance", data, other, densify=densify, **kwargs
        )
    else:
        raise NotImplementedError(
            f"shapely >= 2.0 or PyGEOS is required, "
            f"version {shapely.__version__} is installed"
        )


def buffer(data, distance, resolution=16, **kwargs):
    if compat.USE_SHAPELY_20:
        if compat.SHAPELY_G_20a1:
            return shapely.buffer(data, distance, quad_segs=resolution, **kwargs)
        else:
            # TODO: temporary keep this (so geopandas works with latest released
            # shapely, currently alpha1) until shapely beta1 is out
            return shapely.buffer(data, distance, quadsegs=resolution, **kwargs)
    elif compat.USE_PYGEOS:
        return pygeos.buffer(data, distance, quadsegs=resolution, **kwargs)
    else:
        out = np.empty(len(data), dtype=object)
        if isinstance(distance, np.ndarray):
            if len(distance) != len(data):
                raise ValueError(
                    "Length of distance sequence does not match "
                    "length of the GeoSeries"
                )

            with compat.ignore_shapely2_warnings():
                out[:] = [
                    geom.buffer(dist, resolution, **kwargs)
                    if geom is not None
                    else None
                    for geom, dist in zip(data, distance)
                ]
            return out

        with compat.ignore_shapely2_warnings():
            out[:] = [
                geom.buffer(distance, resolution, **kwargs)
                if geom is not None
                else None
                for geom in data
            ]
        return out


def interpolate(data, distance, normalized=False):
    if compat.USE_SHAPELY_20:
        return shapely.line_interpolate_point(data, distance, normalized=normalized)
    elif compat.USE_PYGEOS:
        try:
            return pygeos.line_interpolate_point(data, distance, normalized=normalized)
        except TypeError:  # support for pygeos<0.9
            return pygeos.line_interpolate_point(data, distance, normalize=normalized)
    else:
        out = np.empty(len(data), dtype=object)
        if isinstance(distance, np.ndarray):
            if len(distance) != len(data):
                raise ValueError(
                    "Length of distance sequence does not match "
                    "length of the GeoSeries"
                )
            with compat.ignore_shapely2_warnings():
                out[:] = [
                    geom.interpolate(dist, normalized=normalized)
                    for geom, dist in zip(data, distance)
                ]
            return out

        with compat.ignore_shapely2_warnings():
            out[:] = [
                geom.interpolate(distance, normalized=normalized) for geom in data
            ]
        return out


def simplify(data, tolerance, preserve_topology=True):
    if compat.USE_SHAPELY_20:
        return shapely.simplify(data, tolerance, preserve_topology=preserve_topology)
    elif compat.USE_PYGEOS:
        # preserve_topology has different default as pygeos!
        return pygeos.simplify(data, tolerance, preserve_topology=preserve_topology)
    else:
        # method and not a property -> can't use _unary_geo
        out = np.empty(len(data), dtype=object)
        with compat.ignore_shapely2_warnings():
            out[:] = [
                geom.simplify(tolerance, preserve_topology=preserve_topology)
                for geom in data
            ]
        return out


def _shapely_normalize(geom):
    """
    Small helper function for now because it is not yet available in Shapely.
    """
    from shapely.geos import lgeos
    from shapely.geometry.base import geom_factory
    from ctypes import c_void_p, c_int

    lgeos._lgeos.GEOSNormalize_r.restype = c_int
    lgeos._lgeos.GEOSNormalize_r.argtypes = [c_void_p, c_void_p]

    geom_cloned = lgeos.GEOSGeom_clone(geom._geom)
    lgeos._lgeos.GEOSNormalize_r(lgeos.geos_handle, geom_cloned)
    return geom_factory(geom_cloned)


def normalize(data):
    if compat.USE_SHAPELY_20:
        return shapely.normalize(data)
    elif compat.USE_PYGEOS:
        return pygeos.normalize(data)
    elif compat.SHAPELY_GE_18:
        out = np.empty(len(data), dtype=object)
        with compat.ignore_shapely2_warnings():
            out[:] = [geom.normalize() if geom is not None else None for geom in data]
    else:
        out = np.empty(len(data), dtype=object)
        with compat.ignore_shapely2_warnings():
            out[:] = [
                _shapely_normalize(geom) if geom is not None else None for geom in data
            ]
    return out


def make_valid(data):
    if compat.USE_SHAPELY_20:
        return shapely.make_valid(data)
    elif compat.USE_PYGEOS:
        return pygeos.make_valid(data)
    elif not compat.SHAPELY_GE_18:
        raise NotImplementedError(
            f"shapely >= 1.8 or PyGEOS is required, "
            f"version {shapely.__version__} is installed"
        )
    else:
        out = np.empty(len(data), dtype=object)
        with compat.ignore_shapely2_warnings():
            out[:] = [
                shapely.validation.make_valid(geom) if geom is not None else None
                for geom in data
            ]
    return out


def project(data, other, normalized=False):
    if compat.USE_SHAPELY_20:
        return shapely.line_locate_point(data, other, normalized=normalized)
    elif compat.USE_PYGEOS:
        try:
            return pygeos.line_locate_point(data, other, normalized=normalized)
        except TypeError:  # support for pygeos<0.9
            return pygeos.line_locate_point(data, other, normalize=normalized)
    else:
        return _binary_op("project", data, other, normalized=normalized)


def relate(data, other):
    if compat.USE_SHAPELY_20:
        return shapely.relate(data, other)
    data = to_shapely(data)
    if isinstance(other, np.ndarray):
        other = to_shapely(other)
    return _binary_op("relate", data, other)


def unary_union(data):
    warning_msg = (
        "`unary_union` returned None due to all-None GeoSeries. In future, "
        "`unary_union` will return 'GEOMETRYCOLLECTION EMPTY' instead."
    )

    if compat.USE_SHAPELY_20:
        data = shapely.union_all(data)
        if data is None or data.is_empty:  # shapely 2.0a1 and 2.0
            warnings.warn(
                warning_msg,
                FutureWarning,
                stacklevel=4,
            )
            return None
        else:
            return data
    elif compat.USE_PYGEOS:
        result = _pygeos_to_shapely(pygeos.union_all(data))
        if result is None:
            warnings.warn(
                warning_msg,
                FutureWarning,
                stacklevel=4,
            )
        return result
    else:
        data = [g for g in data if g is not None]
        if data:
            return shapely.ops.unary_union(data)
        else:
            warnings.warn(
                warning_msg,
                FutureWarning,
                stacklevel=4,
            )
            return None


#
# Coordinate related properties
#


def get_x(data):
    if compat.USE_SHAPELY_20:
        return shapely.get_x(data)
    elif compat.USE_PYGEOS:
        return pygeos.get_x(data)
    else:
        return _unary_op("x", data, null_value=np.nan)


def get_y(data):
    if compat.USE_SHAPELY_20:
        return shapely.get_y(data)
    elif compat.USE_PYGEOS:
        return pygeos.get_y(data)
    else:
        return _unary_op("y", data, null_value=np.nan)


def get_z(data):
    if compat.USE_SHAPELY_20:
        return shapely.get_z(data)
    elif compat.USE_PYGEOS:
        return pygeos.get_z(data)
    else:
        data = [geom.z if geom.has_z else np.nan for geom in data]
        return np.array(data, dtype=np.dtype(float))


def bounds(data):
    if compat.USE_SHAPELY_20:
        return shapely.bounds(data)
    elif compat.USE_PYGEOS:
        return pygeos.bounds(data)
    # ensure that for empty arrays, the result has the correct shape
    if len(data) == 0:
        return np.empty((0, 4), dtype="float64")
    # need to explicitly check for empty (in addition to missing) geometries,
    # as those return an empty tuple, not resulting in a 2D array
    bounds = np.array(
        [
            geom.bounds
            if not (geom is None or geom.is_empty)
            else (np.nan, np.nan, np.nan, np.nan)
            for geom in data
        ]
    )
    return bounds


#
# Coordinate transformation
#


def transform(data, func):
    if compat.USE_SHAPELY_20 or compat.USE_PYGEOS:
        if compat.USE_SHAPELY_20:
            has_z = shapely.has_z(data)
            from shapely import get_coordinates, set_coordinates
        else:
            has_z = pygeos.has_z(data)
            from pygeos import get_coordinates, set_coordinates

        result = np.empty_like(data)

        coords = get_coordinates(data[~has_z], include_z=False)
        new_coords_z = func(coords[:, 0], coords[:, 1])
        result[~has_z] = set_coordinates(data[~has_z].copy(), np.array(new_coords_z).T)

        coords_z = get_coordinates(data[has_z], include_z=True)
        new_coords_z = func(coords_z[:, 0], coords_z[:, 1], coords_z[:, 2])
        result[has_z] = set_coordinates(data[has_z].copy(), np.array(new_coords_z).T)

        return result
    else:
        from shapely.ops import transform

        n = len(data)
        result = np.empty(n, dtype=object)
        for i in range(n):
            geom = data[i]
            if isna(geom):
                result[i] = geom
            else:
                result[i] = transform(func, geom)

        return result
