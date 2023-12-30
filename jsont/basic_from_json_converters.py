from abc import ABC, abstractmethod
from inspect import isclass
from types import NoneType
from typing import (Any, Callable, Generic, Iterable, List, Literal, Mapping, Sequence, Type,
                    TypeVar, Union, cast, get_args)

from jsont.base_types import Json, JsonSimple

T = TypeVar("T")
S = TypeVar("S")
R = TypeVar("R")


class FromJsonConverter(ABC, Generic[T]):
    """The base-class for converters that convert from objects representing json.

    Converters that convert from objects representing json to their specific python object have to
    implement the two abstract methods defined in this base-class.
    """

    @abstractmethod
    def can_convert(self, target_type: type, origin_of_generic: type) -> bool:
        """Return if this converts from an object representing json into the given `target_type`.

        Args:
            target_type: the type this converter may or may not convert an object that represents
                json into.
            origin_of_generic: the unsubscripted version of ``target_type`` (i.e. without
                type-parameters). This origin is computed with :func:`typing.get_origin`.
        Returns:
            `true` if this converter can convert into `target_type`, `false` otherwise.
        """

    @abstractmethod
    def convert(self,
                js: Json,
                target_type: Type[T],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, Type[S]], S]) -> T:
        """Convert the given object representing json to the given target type.

        Args:
            js: the json-representation to convert
            target_type: the type to convert to
            annotations: the annotations dict for ``cl`` as returned by
                :func:`inspect.get_annotations`
            from_json: If this converter converts into container types like :class:`typing.Sequence`
                this function is used to convert the contained json-nodes into their respective
                target-types.
        Returns:
            the converted object of type ``cl``
        Raises:
            ValueError: If the json-representation cannot be converted an instance of ``cl``.
        """


class ToAny(FromJsonConverter[Any]):
    """Convert to the target type :class:`typing.Any`.

    This converter returns the object representing json unchanged.
    """

    def can_convert(self, target_type: type, origin_of_generic: type) -> bool:
        return target_type is Any

    def convert(self,
                js: Json,
                target_type: Type[Any],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, Type[S]], S]) -> Any:
        return cast(Any, js)


class ToUnion(FromJsonConverter[T]):
    """Convert to one of the type-parameters of the given :class:`typing.Union`.

    It tries to convert the object representing json to one of the type-parameters
    of the ``Union``-type in the order of their occurrence and returns the
    first successful conversion result. If none is successful it raises a
    :exc:`ValueError`.

    A ``target_type`` like ``Union[int, str]`` can be used to convert
    for example a ``5`` or a ``"Hello World!"``, but will fail to convert
    a ``list``.
    """

    def can_convert(self, target_type: type, origin_of_generic: type) -> bool:
        return origin_of_generic is Union

    def convert(self,
                js: Json,
                target_type: Type[T],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, Type[S]], S]) -> T:
        union_types = get_args(target_type)
        # a str is also a Sequence of str so check str first to avoid that
        # it gets converted to a Sequence of str
        union_types_with_str_first = (([str] if str in union_types else [])
                                      + [ty for ty in union_types if ty is not str])
        res_or_failures = _first_success(from_json,
                                         ((js, ty) for ty in union_types_with_str_first))
        if res_or_failures \
                and isinstance(res_or_failures, list) \
                and all(isinstance(e, ValueError) for e in res_or_failures):
            raise ValueError(f"Cannot convert {js} to any of {union_types_with_str_first}: "
                             f"{list(zip(union_types_with_str_first, res_or_failures))}")
        return cast(T, res_or_failures)


class ToLiteral(FromJsonConverter[T]):
    """Convert to one of the listet literals.

    Returns the json-representation unchanged if it equals one of the literals, otherwise
    it raises a :exc:`ValueError`

    A ``target_type`` like ``Literal[5, 6]`` can be used to convert
    for example a ``5`` or a ``6``, but not a ``7``.
    """

    def can_convert(self, target_type: type, origin_of_generic: type) -> bool:
        return origin_of_generic is Literal

    def convert(self,
                js: Json,
                target_type: Type[T],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, Type[S]], S]) -> T:
        literals = get_args(target_type)
        if js in literals:
            return cast(T, js)
        raise ValueError(f"Cannot convert {js} to any of {literals}")


class ToNone(FromJsonConverter[None]):
    """Return the json-representation, if it is ``None``.

    If the given json-representation is not ``None`` it raises an :exc:`ValueError`.
    """

    def can_convert(self, target_type: type, origin_of_generic: type) -> bool:
        return target_type is NoneType or target_type is None

    def convert(self,
                js: Json,
                target_type: Type[Any],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, Type[S]], S]) -> None:
        if js is None:
            return None
        raise ValueError(f"Cannot convert {js} to None")


class ToSimple(FromJsonConverter[T]):
    """Return the json-representation, if it is one of the types ``int, float, str, bool``."""

    def can_convert(self, target_type: type, origin_of_generic: type) -> bool:
        return isclass(target_type) and issubclass(target_type, get_args(JsonSimple))

    def convert(self,
                js: Json,
                target_type: Type[T],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, Type[S]], S]) -> T:
        if isinstance(js, target_type):
            return js
        raise ValueError(f"Cannot convert {js} to {target_type}")


class ToTuple(FromJsonConverter[T]):
    """Convert an array to a :class:`tuple`.

    Convert the elements of the array in the corresponding target type given by the type-parameter
    of the :class:`tuple` in the same position as the element. Raises :exc:`ValueError` if
    the number of type-parameters do not match to the number of elements.

    The type-parameters may contain a single ``...`` which is replaced by as many ``Any`` such that
    the number of type-parameters equals the number of elements. So a target type of
    ``tuple[int, ..., str]`` is equivalent to a target type of ``tuple[int, Any, Any, Any, str]``
    if the json-representation to be converted is a :class:`typing.Sequence` of 5 elements.

    A target type like ``tuple[int, str]`` can convert for example the list ``[5, "Hello World!"]``
    into the tuple ``(5, "Hello World!")``, but not ``["Hello World!" 5]``
    """

    def can_convert(self, target_type: type, origin_of_generic: type) -> bool:
        return isclass(origin_of_generic) and issubclass(origin_of_generic, tuple)

    def convert(self,
                js: Json,
                target_type: Type[T],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, Type[S]], S]) -> T:
        element_types: Sequence[Any] = get_args(target_type)
        if element_types.count(...) > 1:
            raise ValueError(f"Cannot convert {js} to {target_type} "
                             f"as {target_type} has more than one ... parameter")
        if isinstance(js, Sequence):
            element_types = _replace_ellipsis(element_types, len(js))
            if len(js) != len(element_types):
                raise ValueError(
                    f"Cannot convert {js} to {target_type} "
                    "as number of type parameter do not match")
            return cast(T, tuple(from_json(e, ty) for e, ty in zip(js, element_types)))
        raise ValueError(f"Cannot convert {js} to {target_type} as types are not convertible")


class ToSequence(FromJsonConverter[T]):
    """Convert an array to a :class:`typing.Sequence`.

    Convert all elements of the array into the corresponding target type given by the type-parameter
    of the :class:`typing.Sequence`.

    A target type of ``Sequence[int]`` can convert a ``list`` of ``int``,
    but not a ``list`` of ``str``.
    """

    def can_convert(self, target_type: type, origin_of_generic: type) -> bool:
        return isclass(origin_of_generic) and issubclass(cast(type, origin_of_generic), Sequence)

    def convert(self,
                js: Json,
                target_type: Type[T],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, Type[S]], S]) -> T:
        element_types = get_args(target_type) or (Any,)
        assert len(element_types) == 1
        if isinstance(js, Sequence):
            return cast(T, [from_json(e, element_types[0]) for e in js])
        raise ValueError(f"Cannot convert {js} to {target_type}")


class ToMapping(FromJsonConverter[T]):
    """Convert the json-representation to a :class:`typing.Mapping`.

    Convert all entries of the given ``Mapping`` (respectively json-object) into entries of a
    ``Mapping`` with the given key and value target types.

    A target type of ``Mapping[str, int]`` can convert for example ``{ "key1": 1, "key2": 2 }``.
    """

    def can_convert(self, target_type: type, origin_of_generic: type) -> bool:
        return isclass(origin_of_generic) and issubclass(cast(type, origin_of_generic), Mapping)

    def convert(self,
                js: Json,
                target_type: Type[T],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, Type[S]], S]) -> T:
        key_value_types = get_args(target_type) or (str, Any)
        key_type, value_type = key_value_types
        if key_type is not str:
            raise ValueError(f"Cannot convert {js} to mapping with key-type: {key_type}")
        if isinstance(js, Mapping):
            return cast(T, {k: from_json(v, value_type) for k, v in js.items()})
        raise ValueError(f"Cannot convert {js} to {target_type}")


class ToTypedMapping(FromJsonConverter[T]):
    """Convert the json-representation to a :class:`typing.TypedDict`.

    Convert all entries of the given ``Mepping`` (respectively json-object) into entries of a
    ``TypedDict`` with the given key and value target types.

    Example:
        >>> from typing import TypedDict
        >>>
        >>> # using the ToTypedMapping converter one can convert for example:
        >>> {"k1": 1.0, "k2": 2, "un": "known"},
        >>> # into the following:
        >>> class Map(TypedDict):
        ...     k1: float
        ...     k2: int
        >>> # In this example the result will meet:
        >>> # assert result == {"k1": 1.0, "k2": 2}

    """

    def __init__(self, strict: bool = False):
        """Initialize an instance of this class.

        Args:
            strict: indicates if the conversion of a ``Mapping`` should fail, if is contains more
                keys than the provided target type. Pass ``True`` to make it fail in this case.
                Defaults to ``False``.
        """
        self.strict = strict

    def can_convert(self, target_type: type, origin_of_generic: type) -> bool:
        return isclass(target_type) and issubclass(target_type, Mapping)

    def convert(self,
                js: Json,
                target_type: Type[T],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, Type[S]], S]) -> T:
        def type_for_key(k: str) -> Type[S]:
            t = annotations.get(k)
            if t:
                return cast(Type[S], t)
            raise ValueError(f"Cannot convert {js} to {target_type} as it contains unknown key {k}")

        if isinstance(js, Mapping) and hasattr(target_type, "__required_keys__"):
            if target_type.__required_keys__.issubset(frozenset(js.keys())):  # type: ignore
                items = js.items() if self.strict \
                    else [(k, v) for k, v in js.items() if k in annotations]
                return cast(T, {k: from_json(v, type_for_key(k)) for k, v in items})
            raise ValueError(
                f"Cannot convert {js} to {target_type} "
                "as it does not contain all required keys "
                f"{target_type.__required_keys__}"  # type: ignore
            )
        raise ValueError(f"Cannot convert {js} to {target_type}")


def _first_success(f: Callable[..., R], i: Iterable[tuple]) -> Union[R, Sequence[ValueError]]:
    failures: List[ValueError] = []
    for args in i:
        try:
            return f(*args)
        except ValueError as e:
            failures.append(e)
    return failures


def _replace_ellipsis(element_types: Sequence[Any], expected_len: int) -> Sequence[Any]:
    if ... in element_types:
        element_types = _fill_ellipsis(element_types, expected_len, Any)  # type: ignore
    return element_types


def _fill_ellipsis(types: Sequence[Any], expected_len: int, fill_type: Type[T]) \
        -> Sequence[Type[T]]:
    types = list(types)
    ellipsis_idx = types.index(...)
    types[ellipsis_idx:ellipsis_idx + 1] = [fill_type] * (expected_len - len(types) + 1)
    return types
