from typing import Dict, Iterable, List, TypeVar, Mapping, cast

from mypy.types import (
    Type, Instance, CallableType, TypeVisitor, UnboundType, AnyType,
    NoneType, TypeVarType, Overloaded, TupleType, TypedDictType, UnionType,
    ErasedType, PartialType, DeletedType, UninhabitedType, TypeType, TypeVarId,
    FunctionLike, TypeVarDef, LiteralType, get_proper_type, ProperType
)


def expand_type(typ: Type, env: Mapping[TypeVarId, Type]) -> ProperType:
    """Substitute any type variable references in a type given by a type
    environment.
    """

    return typ.accept(ExpandTypeVisitor(env))


def expand_type_by_instance(typ: Type, instance: Instance) -> ProperType:
    """Substitute type variables in type using values from an Instance.
    Type variables are considered to be bound by the class declaration."""
    typ = get_proper_type(typ)

    if instance.args == []:
        return typ
    else:
        variables = {}  # type: Dict[TypeVarId, Type]
        for binder, arg in zip(instance.type.defn.type_vars, instance.args):
            variables[binder.id] = arg
        return expand_type(typ, variables)


F = TypeVar('F', bound=FunctionLike)


def freshen_function_type_vars(callee: F) -> F:
    """Substitute fresh type variables for generic function type variables."""
    if isinstance(callee, CallableType):
        if not callee.is_generic():
            return cast(F, callee)
        tvdefs = []
        tvmap = {}  # type: Dict[TypeVarId, Type]
        for v in callee.variables:
            tvdef = TypeVarDef.new_unification_variable(v)
            tvdefs.append(tvdef)
            tvmap[v.id] = TypeVarType(tvdef)
        fresh = cast(CallableType, expand_type(callee, tvmap)).copy_modified(variables=tvdefs)
        return cast(F, fresh)
    else:
        assert isinstance(callee, Overloaded)
        fresh_overload = Overloaded([freshen_function_type_vars(item)
                                     for item in callee.items()])
        return cast(F, fresh_overload)


class ExpandTypeVisitor(TypeVisitor[ProperType]):
    """Visitor that substitutes type variables with values."""

    variables = None  # type: Mapping[TypeVarId, Type]  # TypeVar id -> TypeVar value

    def __init__(self, variables: Mapping[TypeVarId, Type]) -> None:
        self.variables = variables

    def visit_unbound_type(self, t: UnboundType) -> ProperType:
        return t

    def visit_any(self, t: AnyType) -> ProperType:
        return t

    def visit_none_type(self, t: NoneType) -> ProperType:
        return t

    def visit_uninhabited_type(self, t: UninhabitedType) -> ProperType:
        return t

    def visit_deleted_type(self, t: DeletedType) -> ProperType:
        return t

    def visit_erased_type(self, t: ErasedType) -> ProperType:
        # Should not get here.
        raise RuntimeError()

    def visit_instance(self, t: Instance) -> ProperType:
        args = self.expand_types(t.args)
        return Instance(t.type, args, t.line, t.column)

    def visit_type_var(self, t: TypeVarType) -> ProperType:
        repl = get_proper_type(self.variables.get(t.id, t))
        if isinstance(repl, Instance):
            inst = repl
            # Return copy of instance with type erasure flag on.
            return Instance(inst.type, inst.args, line=inst.line,
                            column=inst.column, erased=True)
        else:
            return repl

    def visit_callable_type(self, t: CallableType) -> ProperType:
        return t.copy_modified(arg_types=self.expand_types(t.arg_types),
                               ret_type=t.ret_type.accept(self))

    def visit_overloaded(self, t: Overloaded) -> ProperType:
        items = []  # type: List[CallableType]
        for item in t.items():
            new_item = item.accept(self)
            assert isinstance(new_item, CallableType)
            items.append(new_item)
        return Overloaded(items)

    def visit_tuple_type(self, t: TupleType) -> ProperType:
        return t.copy_modified(items=self.expand_types(t.items))

    def visit_typeddict_type(self, t: TypedDictType) -> ProperType:
        return t.copy_modified(item_types=self.expand_types(t.items.values()))

    def visit_literal_type(self, t: LiteralType) -> ProperType:
        # TODO: Verify this implementation is correct
        return t

    def visit_union_type(self, t: UnionType) -> ProperType:
        # After substituting for type variables in t.items,
        # some of the resulting types might be subtypes of others.
        return UnionType.make_simplified_union(self.expand_types(t.items), t.line, t.column)

    def visit_partial_type(self, t: PartialType) -> ProperType:
        return t

    def visit_type_type(self, t: TypeType) -> ProperType:
        # TODO: Verify that the new item type is valid (instance or
        # union of instances or Any).  Sadly we can't report errors
        # here yet.
        item = t.item.accept(self)
        return TypeType.make_normalized(item)

    def expand_types(self, types: Iterable[Type]) -> List[Type]:
        a = []  # type: List[Type]
        for t in types:
            a.append(t.accept(self))
        return a
