import asyncio
# import pytest
import logging
import typing
import uuid
import strawberry
import typing
from collections import deque

from pathlib import Path
from typing import Annotated, Optional, List, Dict, Tuple

from graphql import parse
from graphql import specified_scalar_types
from graphql import parse, build_ast_schema
from graphql.language import (
    DocumentNode,
    ObjectTypeDefinitionNode,
    FieldDefinitionNode,
    DirectiveNode,
    StringValueNode,
    TypeNode,
    ArgumentNode,
    InputObjectTypeDefinitionNode,
    ScalarTypeDefinitionNode,
    UnionTypeDefinitionNode,
    NamedTypeNode,
    NonNullTypeNode,
    ListTypeNode,
)

def get_scalar_names(sdl_doc: DocumentNode) -> set:
    # 1) základní GraphQL scalary
    builtin = {"Int", "Float", "String", "Boolean", "ID"}

    # 2) custom scalars z SDL
    custom = {
        d.name.value
        for d in sdl_doc.definitions
        if isinstance(d, ScalarTypeDefinitionNode)
    }

    return builtin | custom

def unwrap_type(type_node):
    """
    Unwraps NON_NULL and LIST wrappers to get the base NamedTypeNode.
    """
    t = type_node
    while isinstance(t, (NonNullTypeNode, ListTypeNode)):
        t = t.type
    return t


def select_ast_by_path(
    sdl_doc: DocumentNode,
    path: typing.List[str]
) -> typing.Optional[typing.Union[ObjectTypeDefinitionNode, FieldDefinitionNode]]:
    """
    Traverses the GraphQL AST based on `path`:
      - First element of path selects a type from document.definitions.
      - Subsequent elements select fields from the current type.
      - After selecting a field (if not at end of path), continues into that field's return type definition.
    Returns the final AST node (type or field), or None if any step fails.
    """
    current_node: typing.Union[DocumentNode, ObjectTypeDefinitionNode, FieldDefinitionNode] = sdl_doc
    for idx, name in enumerate(path):
        if isinstance(current_node, DocumentNode):
            # Find the type definition
            type_def = next(
                (
                    d for d in sdl_doc.definitions
                    if isinstance(d, ObjectTypeDefinitionNode) and d.name.value == name
                ),
                None
            )
            if not type_def:
                return None
            current_node = type_def
        elif isinstance(current_node, ObjectTypeDefinitionNode):
            # Find the field in the type
            field_def = next(
                (f for f in current_node.fields if f.name.value == name),
                None
            )
            if not field_def:
                return None
            current_node = field_def
            # If more path remains, dive into the field's return type definition
            if idx < len(path) - 1:
                type_name = unwrap_type(field_def.type)
                type_def = next(
                    (
                        d for d in sdl_doc.definitions
                        if isinstance(d, ObjectTypeDefinitionNode) and d.name.value == type_name
                    ),
                    None
                )
                if not type_def:
                    return None
                current_node = type_def
        else:
            # Unexpected node type
            return None
    return current_node

def get_read_scalar_values(sdl_doc: DocumentNode) -> dict:
    """
    Extracts a mapping of GraphQL object type names to query field names 
    that return a single object by NON_NULL 'id' argument.

    This function analyzes the 'Query' type in the provided GraphQL SDL AST (DocumentNode).
    For every field in the Query type that:
      - has exactly one argument,
      - the argument is named 'id' and is NonNull,
      - the field returns a named OBJECT type,
    it adds a mapping from the returned object type name to a list of field names
    (query names) that provide lookup by ID.

    This is useful for identifying "detail" (read-by-id) queries for specific types,
    e.g. for scaffolding detail page code or introspection.

    Args:
        sdl_doc (DocumentNode): Parsed GraphQL SDL document (AST).

    Returns:
        dict[str, list[str]]: 
            Dictionary where keys are GraphQL OBJECT type names,
            and values are lists of Query field names that return this type by a single 'id' argument.

    Example:
        # For SDL like:
        # type Query {
        #   user(id: ID!): User
        #   group(id: Int!): Group
        #   search(term: String!): [User]
        # }
        #
        # get_read_scalar_values(sdl_doc)
        # -> {'User': ['user'], 'Group': ['group']}

    """
    result = {}

    # sdl_doc is already a parsed DocumentNode
    # Find the Query type definition node
    query_def = next(
        (
            defn for defn in sdl_doc.definitions
            if isinstance(defn, ObjectTypeDefinitionNode)
            and defn.name.value == "Query"
        ),
        None
    )
    if not query_def or not query_def.fields:
        return result

    # Inspect each field in Query
    for field in query_def.fields:
        args = field.arguments or []
        # Must have exactly one argument named "id" which is NON_NULL
        if (
            len(args) == 1
            and args[0].name.value == "id"
            and isinstance(args[0].type, NonNullTypeNode)
        ):
            # Unwrap return type
            ret_base = unwrap_type(field.type)
            # If the return type is a NamedTypeNode (OBJECT), record it
            if isinstance(ret_base, NamedTypeNode):
                obj_name = ret_base.name.value
                if obj_name not in result:
                    result[obj_name] = []
                result[obj_name].append(field.name.value)

    return result

def get_read_vector_values(sdl_doc: DocumentNode) -> dict:
    """
    Extracts a mapping of GraphQL object type names to Query field names
    that return a NonNull list of NonNull objects of that type.

    Specifically, this function searches the 'Query' type in the provided SDL AST.
    For every field in the Query type where the return type is:
      NonNull(List(NonNull(NamedType)))
    (that is, [ObjectType!]!),
    it adds a mapping from the object type name to a list of Query field names
    that return this vector.

    Args:
        sdl_doc (DocumentNode): Parsed GraphQL SDL document (AST).

    Returns:
        dict[str, list[str]]:
            Dictionary where keys are OBJECT type names,
            and values are lists of Query field names returning [Type!]!.

    Example:
        # For SDL like:
        # type Query {
        #   users: [User!]!
        #   groups: [Group!]!
        #   findUser(id: ID!): User
        # }
        #
        # get_read_vector_values(sdl_doc)
        # -> {'User': ['users'], 'Group': ['groups']}

    """
    result = {}

    # najdi Query type definition v AST
    query_def = next(
        (
            defn for defn in sdl_doc.definitions
            if isinstance(defn, ObjectTypeDefinitionNode)
            and defn.name.value == "Query"
        ),
        None
    )
    if not query_def or not query_def.fields:
        return result

    for field in query_def.fields:
        t = field.type
        # NON_NULL
        if isinstance(t, NonNullTypeNode):
            list_node = t.type
            # LIST
            if isinstance(list_node, ListTypeNode):
                inner = list_node.type
                # NON_NULL
                if isinstance(inner, NonNullTypeNode):
                    base = inner.type
                    # OBJECT represented by NamedTypeNode
                    if isinstance(base, NamedTypeNode):
                        type_name  = base.name.value
                        if type_name not in result:
                            result[type_name] = []
                        field_name = field.name.value
                        result[type_name].append(field_name)

    return result


def get_insert_mutations(sdl_doc: DocumentNode) -> dict:
    """
    Extracts a mapping of GraphQL object type names to mutation field names
    for insert-like mutations, according to specific conventions.

    This function searches the SDL AST for 'Mutation' type fields that:
      - Have exactly one argument, which must be NON_NULL and of INPUT_OBJECT type.
      - The input type must NOT contain a required field named 'lastchange'.
      - The return type must be a UNION, where at least one member is an OBJECT
        type that does not have 'Error' in its name.

    For each such mutation, the function maps the OBJECT type name(s) returned
    by the union (excluding error types) to the mutation field name.

    Args:
        sdl_doc (DocumentNode): Parsed GraphQL SDL document (AST).

    Returns:
        dict[str, list[str]]:
            Dictionary where keys are OBJECT type names and values are lists of
            mutation field names that perform inserts for that object type.

    Example:
        # Given the following SDL:
        # type Mutation {
        #   insertUser(input: UserInput!): InsertUserResult!
        # }
        # union InsertUserResult = User | UserInsertError
        #
        # get_insert_mutations(sdl_doc)
        # -> {'User': ['insertUser']}

    """
    result = {}

    # najdi Mutation type definition v AST
    mutation_def = next(
        (
            defn for defn in sdl_doc.definitions
            if isinstance(defn, ObjectTypeDefinitionNode)
            and defn.name.value == "Mutation"
        ),
        None
    )
    if not mutation_def or not mutation_def.fields:
        return result

    # iteruj přes všechna pole mutací
    for field in mutation_def.fields:
        args = field.arguments or []
        # hledáme přesně jeden NON_NULL arg
        if len(args) == 1 and isinstance(args[0].type, NonNullTypeNode):
            # unwrapneme na base input type
            base_arg = unwrap_type(args[0].type)
            # musí být INPUT_OBJECT
            input_def = next(
                (d for d in sdl_doc.definitions
                 if isinstance(d, InputObjectTypeDefinitionNode)
                 and d.name.value == base_arg.name.value),
                None
            )
            if not input_def:
                continue
            # zkontrolujeme, že inputFields neobsahuje "lastchange"
            input_field_names = [f.name.value for f in input_def.fields or []]
            if "lastchange" in input_field_names:
                continue

            # unwrap return type
            ret_base = unwrap_type(field.type)
            # musí být UNION
            union_def = next(
                (d for d in sdl_doc.definitions
                 if isinstance(d, UnionTypeDefinitionNode)
                 and d.name.value == ret_base.name.value),
                None
            )
            if not union_def:
                continue

            # pro každou možnou typovou variantu v unii
            for pt in union_def.types or []:  # NamedTypeNode
                # jen OBJECT a bez "Error" v názvu
                if isinstance(pt, NamedTypeNode) and "Error" not in pt.name.value:
                    # ověříme, že je to skutečný ObjectTypeDefinition
                    obj_def = next(
                        (d for d in sdl_doc.definitions
                         if isinstance(d, ObjectTypeDefinitionNode)
                         and d.name.value == pt.name.value),
                        None
                    )
                    if obj_def:
                        type_name = pt.name.value
                        if type_name not in result:
                            result[type_name] = []

                        result[type_name].append(field.name.value)

    return result

def get_update_mutations(sdl_doc: DocumentNode) -> dict:
    """
    Extracts a mapping of GraphQL object type names to mutation field names
    for update-like mutations, according to specific conventions.

    This function searches the SDL AST for 'Mutation' type fields that:
      - Have exactly one argument, which must be NON_NULL and of INPUT_OBJECT type.
      - The input object must have more than two input fields, including required
        (NON_NULL) fields named 'id' and 'lastchange'.
      - The return type must be a UNION, where at least one member is an OBJECT
        type (not containing 'Error' in its name).

    For each such mutation, the function maps the OBJECT type name(s) returned
    by the union (excluding error types) to the mutation field name.

    Args:
        sdl_doc (DocumentNode): Parsed GraphQL SDL document (AST).

    Returns:
        dict[str, list[str]]:
            Dictionary where keys are OBJECT type names and values are lists of
            mutation field names that perform updates for that object type.

    Example:
        # Given SDL:
        # type Mutation {
        #   updateUser(input: UserUpdateInput!): UpdateUserResult!
        # }
        # input UserUpdateInput {
        #   id: ID!
        #   lastchange: DateTime!
        #   name: String
        #   email: String
        # }
        # union UpdateUserResult = User | UserUpdateError
        #
        # get_update_mutations(sdl_doc)
        # -> {'User': ['updateUser']}

    """
    result = {}

    # najdi Mutation type definition v AST
    mutation_def = next(
        (
            defn for defn in sdl_doc.definitions
            if isinstance(defn, ObjectTypeDefinitionNode)
            and defn.name.value == "Mutation"
        ),
        None
    )
    if not mutation_def or not mutation_def.fields:
        return result

    # iteruj přes všechna pole mutací
    for field in mutation_def.fields:
        args = field.arguments or []
        # hledáme jediný NON_NULL INPUT_OBJECT argument
        if len(args) == 1 and isinstance(args[0].type, NonNullTypeNode):
            base_arg = unwrap_type(args[0].type)
            # musí být INPUT_OBJECT
            input_def = next(
                (
                    d for d in sdl_doc.definitions
                    if isinstance(d, InputObjectTypeDefinitionNode)
                    and d.name.value == base_arg.name.value
                ),
                None
            )
            if not input_def:
                continue

            input_fields = input_def.fields or []
            # musí mít více než 2 fields
            if len(input_fields) <= 2:
                continue

            # musí mít povinná id & lastchange
            required = [
                f.name.value for f in input_fields
                if isinstance(f.type, NonNullTypeNode)
            ]
            if not ("id" in required and "lastchange" in required):
                continue

            # unwrap return type must be UNION
            ret_base = unwrap_type(field.type)
            union_def = next(
                (
                    d for d in sdl_doc.definitions
                    if isinstance(d, UnionTypeDefinitionNode)
                    and d.name.value == ret_base.name.value
                ),
                None
            )
            if not union_def:
                continue

            for pt in union_def.types or []:
                if isinstance(pt, NamedTypeNode) and "Error" not in pt.name.value:
                    obj_def = next(
                        (
                            d for d in sdl_doc.definitions
                            if isinstance(d, ObjectTypeDefinitionNode)
                            and d.name.value == pt.name.value
                        ),
                        None
                    )
                    if obj_def:
                        type_name = pt.name.value
                        if type_name not in result:
                            result[type_name] = []
                        result[type_name].append(field.name.value)

    return result


def get_delete_mutations(sdl_doc: DocumentNode) -> dict:
    """
    Extracts a mapping of GraphQL object type names to mutation field names
    for "delete" mutations following a specific convention.

    This function analyzes the SDL AST and looks for mutation fields that:
      - Have exactly one argument, which must be NON_NULL and of INPUT_OBJECT type.
      - The input object must contain *only* two required fields: 'id' and 'lastchange'.
      - The return type must be an OBJECT type, whose fields include an 'Entity' field.
      - The type of the 'Entity' field determines which object type is being deleted.

    For each such mutation, the function maps the object type name (taken from
    the 'Entity' field's type) to the mutation field name(s) that perform deletion
    for that type.

    Args:
        sdl_doc (DocumentNode): Parsed GraphQL SDL document (AST).

    Returns:
        dict[str, list[str]]:
            Dictionary where keys are OBJECT type names (entity types being deleted)
            and values are lists of mutation field names that perform deletion
            for that object type.

    Example:
        # Given SDL:
        # type Mutation {
        #   deleteUser(input: DeleteUserInput!): DeleteUserResult!
        # }
        # input DeleteUserInput {
        #   id: ID!
        #   lastchange: DateTime!
        # }
        # type DeleteUserResult {
        #   Entity: User
        #   success: Boolean
        # }
        #
        # get_delete_mutations(sdl_doc)
        # -> {'User': ['deleteUser']}

    """
    result = {}

    # najdi Mutation type definition v AST
    mutation_def = next(
        (
            defn for defn in sdl_doc.definitions
            if isinstance(defn, ObjectTypeDefinitionNode)
            and defn.name.value == "Mutation"
        ),
        None
    )
    if not mutation_def or not mutation_def.fields:
        return result

    # iteruj přes všechna pole mutací
    for field in mutation_def.fields:
        args = field.arguments or []
        # hledáme jediný NON_NULL INPUT_OBJECT argument
        if len(args) == 1 and isinstance(args[0].type, NonNullTypeNode):
            base_arg = unwrap_type(args[0].type)
            # najdi definici INPUT_OBJECT
            input_def = next(
                (
                    defn for defn in sdl_doc.definitions
                    if isinstance(defn, InputObjectTypeDefinitionNode)
                    and defn.name.value == base_arg.name.value
                ),
                None
            )
            if not input_def:
                continue

            input_fields = input_def.fields or []
            # musí obsahovat právě id & lastchange
            required = [f.name.value for f in input_fields if isinstance(f.type, NonNullTypeNode)]
            if set(required) != {"id", "lastchange"}:
                continue

            # unwrap return type a ověř, že je OBJECT
            ret_base = unwrap_type(field.type)
            if not isinstance(ret_base, NamedTypeNode):
                continue

            # najdi definici návratového objektu
            obj_def = next(
                (
                    defn for defn in sdl_doc.definitions
                    if isinstance(defn, ObjectTypeDefinitionNode)
                    and defn.name.value == ret_base.name.value
                ),
                None
            )
            if not obj_def or not obj_def.fields:
                continue

            # najdi pole 'Entity'
            entity_field = next(
                (f for f in obj_def.fields if f.name.value == 'Entity'),
                None
            )
            if not entity_field:
                continue

            # unwrap type pole 'Entity' a získej jméno
            entity_type = unwrap_type(entity_field.type)
            if isinstance(entity_type, NamedTypeNode):
                type_name = entity_type.name.value
                if type_name not in result:
                    result[type_name] = []
                result[type_name].append(field.name.value)

    return result


def get_cruds(sdl_doc: DocumentNode) -> dict:
    """
    Constructs a CRUD operations mapping for each object type in a GraphQL SDL AST.

    This function combines the outputs of all four extraction helpers:
      - get_read_scalar_values
      - get_read_vector_values
      - get_insert_mutations
      - get_update_mutations
      - get_delete_mutations

    It returns a dictionary where each key is an object type name and the value is
    a dictionary describing which GraphQL operations (read, readp, insert, update, delete)
    are supported for that type. Only types that support both single-item 'read' and
    plural 'readp' (vector) queries are included. The value dict may contain keys:
    'read', 'readp', 'insert', 'update', and 'delete', each mapping to a list of field names.

    Args:
        sdl_doc (DocumentNode): Parsed GraphQL SDL document (AST).

    Returns:
        dict[str, dict[str, list[str]]]:
            Dictionary mapping object type names to supported operation field names.
            Each value is a dictionary that may include keys:
            - 'read': List of single-object query field names.
            - 'readp': List of plural/vector query field names.
            - 'insert': List of insert mutation field names (if any).
            - 'update': List of update mutation field names (if any).
            - 'delete': List of delete mutation field names (if any).

    Example:
        # {
        #   'User': {
        #     'read': ['user'],
        #     'readp': ['users'],
        #     'insert': ['insertUser'],
        #     'update': ['updateUser'],
        #     'delete': ['deleteUser']
        #   },
        #   ...
        # }

    Note:
        A type is only included if it supports both 'read' (single) and 'readp' (vector) queries.

    """
    single = get_read_scalar_values(sdl_doc)
    vector = get_read_vector_values(sdl_doc)
    ins    = get_insert_mutations(sdl_doc)
    upd    = get_update_mutations(sdl_doc)
    dele   = get_delete_mutations(sdl_doc)

    cruds = {}
    for type_name, op_vector in single.items():
        entry = {
            "read": op_vector
        }
        cruds[type_name] = entry
    for type_name, op_vector in vector.items():
        if type_name not in cruds:
            cruds[type_name] = {}
        cruds[type_name]["readp"] = op_vector
    for type_name, op_vector in ins.items():
        if type_name not in cruds:
            cruds[type_name] = {}
        cruds[type_name]["insert"] = op_vector
    for type_name, op_vector in upd.items():
        if type_name not in cruds:
            cruds[type_name] = {}
        cruds[type_name]["update"] = op_vector
    for type_name, op_vector in dele.items():
        if type_name not in cruds:
            cruds[type_name] = {}
        cruds[type_name]["delete"] = op_vector
    
    return cruds


sdlQuery = """
query sdlQuery {
  _service {
    sdl
  }
}"""

def build_selection_optional(sdl_doc: DocumentNode,
                             field_type: TypeNode) -> str:
    """
    Builds a selection set by iterating over fields of the given object type.
    Excludes any field that has at least one NON_NULL argument.
    For fields returning OBJECT or federated types, nests them with `{ __typename id }`.
    Scalar and enum fields are inlined by name.
    """
    scalar_names = get_scalar_names(sdl_doc)

    # 1) Unwrap to the base NamedTypeNode
    base = unwrap_type(field_type)

    # 2) Locate the corresponding ObjectTypeDefinition in the AST
    type_def = next(
        (d for d in sdl_doc.definitions
         if isinstance(d, ObjectTypeDefinitionNode)
         and d.name.value == base.name.value),
        None
    )
    if not type_def or not type_def.fields:
        return ""

    parts = ["__typename"]
    for f in type_def.fields:
        name = f.name.value
        if name.startswith("__"):
            continue

        # skip any field that has at least one NON_NULL argument
        if any(isinstance(arg.type, NonNullTypeNode) for arg in (f.arguments or [])):
            continue

        # determine the unwrapped return type name
        ret_base = unwrap_type(f.type)
        ret_name = ret_base.name.value

        # if it's a scalar or enum, just add the field name
        if ret_name in scalar_names:
            parts.append(name)
        else:
            # otherwise treat it as an object/external/union: only __typename and id
            parts.append(f"{name} {{ __typename id }}")

    if not parts:
        return ""

    # join with indentation for readability
    joined = "\n    ".join(parts)
    return f"{{ {joined} }}"


def build_selection(sdl_doc: DocumentNode, field_type: TypeNode) -> str:
    """
    Recursively builds a selection set based on the AST node of field_type.
    Uses build_selection_optional for OBJECTs, recurses through LIST/NON_NULL,
    and for UNION falls back to `{ __typename }`.
    """
    if field_type is None:
        return ""

    # Unwrap NON_NULL
    if isinstance(field_type, NonNullTypeNode):
        return build_selection(sdl_doc, field_type.type)

    # Unwrap LIST
    if isinstance(field_type, ListTypeNode):
        return build_selection(sdl_doc, field_type.type)

    # Now it must be a NamedTypeNode
    if not isinstance(field_type, NamedTypeNode):
        return ""

    # Try OBJECT
    obj_def = next(
        (d for d in sdl_doc.definitions
         if isinstance(d, ObjectTypeDefinitionNode)
         and d.name.value == field_type.name.value),
        None
    )
    if obj_def:
        result = build_selection_optional(sdl_doc, field_type)
        logging.info(f"{obj_def.name} -> {result}")
        return result

    # Try UNION
    union_def = next(
        (d for d in sdl_doc.definitions
         if isinstance(d, UnionTypeDefinitionNode)
         and d.name.value == field_type.name.value),
        None
    )
    if union_def:
        return "{ __typename }"

    # SCALAR or other kinds → no selection
    return ""

def build_medium_fragment(sdl_doc: DocumentNode, type_name: str, postfix: str = "MediumFragment") -> str:
    """
    Constructs a GraphQL fragment for `type_name` including only fields that:
      - have no NON_NULL arguments,
      - return a base type that is scalar.
    The fragment is named `<TypeName>MediumFragment`.
    """
    # Find the type definition in the AST
    type_def = next(
        (
            d for d in sdl_doc.definitions
            if isinstance(d, ObjectTypeDefinitionNode) and d.name.value == type_name
        ),
        None
    )
    if not type_def or not type_def.fields:
        return f"# Type {type_name} not found or has no fields"

    scalar_names = get_scalar_names(sdl_doc)
    # print(f"scalar_names {scalar_names}")
    parts: typing.List[str] = ["__typename"]

    for field in type_def.fields:  # type: FieldDefinitionNode
        # Skip fields with any required arguments
        # print(f"considering field {field.name.value} / {field}")
        # print(f"considering field {field.arguments or []}")
        if any(isinstance(arg.type, NonNullTypeNode) for arg in (field.arguments or [])):
            continue
        # Unwrap return type
        base = unwrap_type(field.type)
        # print(f"considering field {base.name.value}")
        # Only include scalar return types
        if base.name.value in scalar_names:
            parts.append(field.name.value)
        # else:
        #     print(f"considering field {base.name.value} SKIPPED")

    if not parts:
        return f"fragment {type_name}{postfix} on {type_name} {{ __typename }}"

    fields_str = "\n    ".join(parts)
    return f"fragment {type_name}{postfix} on {type_name} {{ {fields_str} }}"

def build_large_fragment(
    sdl_doc: DocumentNode,
    type_name: str,
    postfix: str = "LargeFragment"
) -> str:
    """
    Constructs a GraphQL fragment for `type_name` including:
      - all medium fragment fields (scalars without required args), plus
      - object/union/list fields without required args, each with a minimal { __typename } sub-selection.

    The fragment is named `<TypeName>LargeFragment`.
    """
    # locate the type
    type_def = next(
        (
            d for d in sdl_doc.definitions
            if isinstance(d, ObjectTypeDefinitionNode) and d.name.value == type_name
        ),
        None
    )
    if not type_def or not type_def.fields:
        return f"# Type {type_name} not found or has no fields"

    scalar_names = get_scalar_names(sdl_doc)
    # collect object and union names for lookup
    object_names = {
        d.name.value
        for d in sdl_doc.definitions
        if isinstance(d, ObjectTypeDefinitionNode)
    }
    union_names = {
        d.name.value
        for d in sdl_doc.definitions
        if isinstance(d, UnionTypeDefinitionNode)
    }

    parts: typing.List[str] = ["__typename"]

    for field in type_def.fields:  # type: FieldDefinitionNode
        # skip if any argument is NonNull
        if any(isinstance(arg.type, NonNullTypeNode) for arg in (field.arguments or [])):
            continue

        base = unwrap_type(field.type)  # NamedTypeNode
        name = base.name.value

        if name in scalar_names:
            # scalar field
            parts.append(field.name.value)

        elif name in object_names :
            # object or union field → minimal sub-selection
            parts.append(f"{field.name.value} {{ __typename id }}")
        elif name in union_names:
            parts.append(f"{field.name.value} {{ __typename }}")

    if not parts:
        return f"fragment {type_name}{postfix} on {type_name} {{ __typename }}"

    fields_str = "\n    ".join(parts)
    return f"fragment {type_name}{postfix} on {type_name} {{ {fields_str} }}"

def print_type(type_node: TypeNode) -> str:
    """
    Prints GraphQL type signature from an AST TypeNode, handling NON_NULL and LIST.
    """
    if type_node is None:
        return ""
    # NON_NULL → recurse then add "!"
    if isinstance(type_node, NonNullTypeNode):
        return f"{print_type(type_node.type)}!"
    # LIST → recurse inside brackets
    if isinstance(type_node, ListTypeNode):
        return f"[{print_type(type_node.type)}]"
    # NamedType → SCALAR, OBJECT, etc.
    if isinstance(type_node, NamedTypeNode):
        return type_node.name.value
    # fallback
    return ""

def build_input_type_params_list(
        sdl_doc: DocumentNode,
        input_type_name: str
    ) -> list[str]:
    """
    Builds parameter definitions string for given INPUT_OBJECT type.
    Outputs GraphQL variable signature, e.g.:
      ($field1: Type1!, $field2: Type2)
    """
    # Najdi definici INPUT_OBJECT v AST
    input_def = next(
        (
            d for d in sdl_doc.definitions
            if isinstance(d, InputObjectTypeDefinitionNode)
            and d.name.value == input_type_name
        ),
        None
    )
    # Pokud není nebo nemá žádná pole, vrať prázdný string
    if not input_def or not input_def.fields:
        return ""

    params = {}
    # Pro každé pole v inputu
    for field in input_def.fields:  # type: InputValueDefinitionNode
        # field.type je TypeNode (NamedType, NonNullType, ListType)
        type_str = print_type(field.type)
        params[field.name.value] = type_str

    return params

def build_input_type_params(sdl_doc: DocumentNode,
                            input_type_name: str) -> str:
    """
    Builds parameter definitions string for given INPUT_OBJECT type.
    Outputs GraphQL variable signature, e.g.:
      ($field1: Type1!, $field2: Type2)
    """

    params = build_input_type_params_list(sdl_doc=sdl_doc, input_type_name=input_type_name)
    if not params:
        return ""
    params_str = [f"${key}: {value}" for key, value in params.items()]
    # Sestav víceliniový signature block
    joined = ",\n   ".join(params_str)
    return f"(\n   {joined}\n)"

def get_mutation_query_params(sdl_doc: DocumentNode, mutation_name: str) -> str:
    # 1) Najdi Mutation type v AST
    mutation_def = next(
        (d for d in sdl_doc.definitions
         if isinstance(d, ObjectTypeDefinitionNode) and d.name.value == "Mutation"),
        None
    )
    if not mutation_def or not mutation_def.fields:
        return ""

    # 2) Najdi konkrétní mutation field
    field = next(
        (f for f in mutation_def.fields if f.name.value == mutation_name),
        None
    )
    if not field or len(field.arguments or []) != 1:
        return ""

    # 3) Jediný NON_NULL INPUT_OBJECT argument
    arg = field.arguments[0]
    base_arg = unwrap_type(arg.type)
    input_name = base_arg.name.value

    # 4) Vygeneruj definici proměnných podle INPUT_OBJECT
    # param_defs = build_input_type_params(sdl_doc, input_name) # build_input_type_params_list
    param_defs = build_input_type_params_list(sdl_doc, input_name) # 
    return param_defs

def build_expanded_mutation(sdl_doc: DocumentNode, mutation_name: str) -> str:
    """
    Builds complete GraphQL mutation string for given mutation.
    Uses expanded individual fields as variables based on input type.
    """
    # 1) Najdi Mutation type v AST
    mutation_def = next(
        (d for d in sdl_doc.definitions
         if isinstance(d, ObjectTypeDefinitionNode) and d.name.value == "Mutation"),
        None
    )
    if not mutation_def or not mutation_def.fields:
        return ""

    # 2) Najdi konkrétní mutation field
    field = next(
        (f for f in mutation_def.fields if f.name.value == mutation_name),
        None
    )
    if not field or len(field.arguments or []) != 1:
        return ""

    # 3) Jediný NON_NULL INPUT_OBJECT argument
    arg = field.arguments[0]
    base_arg = unwrap_type(arg.type)
    input_name = base_arg.name.value

    # 4) Vygeneruj definici proměnných podle INPUT_OBJECT
    param_defs = build_input_type_params(sdl_doc, input_name)

    # 5) Sestav call‑args z input fields
    input_def = next(
        (d for d in sdl_doc.definitions
         if isinstance(d, InputObjectTypeDefinitionNode) and d.name.value == input_name),
        None
    )
    inputs = input_def.fields or []
    call_args = ",\n   ".join(f"{f.name.value}: ${f.name.value}" for f in inputs)

    # 6) Sestav selection podle návratového typu
    ret_base = unwrap_type(field.type)
    selection = ""

    # 6a) Pokud je to UNION
    union_def = next(
        (d for d in sdl_doc.definitions
         if isinstance(d, UnionTypeDefinitionNode) and d.name.value == ret_base.name.value),
        None
    )
    if union_def:
        parts = []
        for pt in union_def.types or []:
            name = pt.name.value
            # jen OBJECT a bez „Error“
            obj_def = next(
                (d for d in sdl_doc.definitions
                 if isinstance(d, ObjectTypeDefinitionNode) and d.name.value == name),
                None
            )
            if obj_def and "Error" not in name:
                sel = build_selection(sdl_doc, NamedTypeNode(name=pt.name))
                parts.append(f"... on {name} {sel}")
        joined = "\n   ".join(parts)
        selection = f" {{\n   __typename\n   {joined}\n }}"
    else:
        # 6b) Pokud je to OBJECT
        obj_def = next(
            (d for d in sdl_doc.definitions
             if isinstance(d, ObjectTypeDefinitionNode) and d.name.value == ret_base.name.value),
            None
        )
        if obj_def:
            sel = build_selection(sdl_doc, ret_base)
            selection = f" {sel}" if sel else ""

    # 7) Poskládáme celý mutation string
    return (
        f"mutation {param_defs} {{\n"
        f"  {mutation_name}({arg.name.value}: {{\n"
        f"   {call_args}\n"
        f"  }}){selection}\n"
        f"}}"
    )

def build_query_page(sdl_doc: DocumentNode, operation_name: str) -> str:
    """
    Builds a readPage query for the given operation name,
    expecting Query.<operationName>: NON_NULL( LIST( NON_NULL( Object ) ) ).
    """
    # 1) Najdi Query type v AST
    query_def = next(
        (d for d in sdl_doc.definitions
         if isinstance(d, ObjectTypeDefinitionNode) and d.name.value == "Query"),
        None
    )
    assert query_def and query_def.fields, "Query type not found or has no fields"

    # 2) Najdi pole s daným jménem
    field_def = next(
        (f for f in query_def.fields if f.name.value == operation_name),
        None
    )
    assert field_def, f"Field {operation_name} not found in Query"

    # 3) Ověření struktury: NON_NULL → LIST → NON_NULL → NamedType
    t = field_def.type
    assert isinstance(t, NonNullTypeNode), f"{operation_name} must be NON_NULL"
    t = t.type
    assert isinstance(t, ListTypeNode), f"{operation_name} must be a LIST"
    t = t.type
    assert isinstance(t, NonNullTypeNode), f"{operation_name} list elements must be NON_NULL"

    # 4) Vytvoření selection setu
    sel = build_selection(sdl_doc, field_def.type)

    # 5) Složení finální query
    return f"query {operation_name} {{ {operation_name}{sel} }}"

def build_query_scalar(sdl_doc: DocumentNode,
                       operation_name: str) -> typing.Optional[str]:
    """
    Builds a read(id) query for given operation name.
    Expects Query.<operationName>(id: ID!): OBJECT.
    """
    # 1) Najdi Query type v AST
    query_def = next(
        (d for d in sdl_doc.definitions
         if isinstance(d, ObjectTypeDefinitionNode) and d.name.value == "Query"),
        None
    )
    if not query_def or not query_def.fields:
        return None

    # 2) Najdi field s daným jménem
    field_def = next(
        (f for f in query_def.fields if f.name.value == operation_name),
        None
    )
    if not field_def:
        return None

    # 3) Unwrap na base NamedType
    field_base = unwrap_type(field_def.type)
    if not isinstance(field_base, NamedTypeNode):
        return None

    # 4) Zjisti, že ten typ opravdu existuje jako OBJECT
    obj_def = next(
        (d for d in sdl_doc.definitions
         if isinstance(d, ObjectTypeDefinitionNode)
         and d.name.value == field_base.name.value),
        None
    )
    if not obj_def:
        return None

    # 5) Sestav selection set
    sel = build_selection(sdl_doc, field_def.type)

    # 6) Vrať finální query s proměnnou $id
    return f"query {operation_name}Read($id: UUID!) {{ {operation_name}(id: $id){sel} }}"

async def test_page(sdl_doc, ops, executor):
    """
    Runs the paged “readp” operation against the parsed SDL DocumentNode.
    """
    assert ops.get("readp") is not None, f"{ops}"
    [operation, *_] = ops.get("readp")
    query = build_query_page(sdl_doc, operation)
    assert query, f"Query for {operation} not found in SDL"
    logging.info(f'query for page\n{query}')
    # no variables needed for page queries
    variable_values = {}
    
    result = await executor(query=query, variable_values=variable_values)
    errors = result.get("errors")
    assert errors is None, f"Error during page execution: {errors}"
    
    data = result.get("data")
    assert data is not None, "Empty response, check resolver for paged query"
    
    page = data.get(operation)
    assert page is not None, "Paged field returned None"
    assert isinstance(page, list) and len(page) > 0, "Paged list is empty"
    
    return page

async def test_scalar(sdl_doc, ops, executor):
    """
    Tests the single-item read (scalar) operation using an ID
    obtained from the paged read.
    """
    # 1) Get the paged result and pick the first entity
    page = await test_page(sdl_doc, ops, executor)
    entity, *_ = page

    # 2) Build and verify the scalar query
    operation, *_ = ops.get("read")
    query = build_query_scalar(sdl_doc, operation)
    assert query, f"Query for {operation} not found in SDL"

    # 3) Prepare variables (ID from the page entity)
    variable_values = {"id": entity["id"]}

    # 4) Execute and validate
    result = await executor(query=query, variable_values=variable_values)
    errors = result.get("errors")
    assert errors is None, f"Error during scalar execution: {errors}"

    data = result.get("data")
    assert data is not None, "Empty response, check resolver for scalar query"

    item = data.get(operation)
    assert item is not None, "Scalar field returned None"
    assert item.get("id") == variable_values["id"], (
        f"ID mismatch, expected {variable_values['id']} but got {item.get('id')}"
    )

    return item

async def test_insert(sdl_doc, ops, executor):
    """
    Tests the insert mutation for a given type, seeding variables
    from an existing entity (minus id & lastchange).
    """
    # 1) Build and verify the insert mutation
    operation, *_ = ops.get("insert")
    query = build_expanded_mutation(sdl_doc, operation)
    assert query, f"Mutation for {operation} not found in SDL"

    # 2) Fetch a template entity from the paged query
    page = await test_page(sdl_doc, ops, executor)
    entity, *_ = page
    
    # 3) Prepare variables by cloning and removing id & lastchange
    variable_values = {**entity}
    variable_values.pop("id", None)
    variable_values.pop("lastchange", None)

    # 4) Execute the insert mutation
    result = await executor(query=query, variable_values=variable_values)
    errors = result.get("errors")
    assert errors is None, f"Error during insert execution: {errors}"

    # 5) Validate response shape
    data = result.get("data")
    assert data is not None, "Empty response, check resolver for insert"
    created = data.get(operation)
    assert created is not None, "Insert mutation returned None"
    assert "Error" not in created.get("__typename", ""), f"{operation} returned error: {created}"
    assert created.get("createdbyId", None) is not None, f"{operation} handles create createdby by wrong way"

    return created

async def test_update(sdl_doc, ops, executor):
    """
    Tests the update mutation for a given type, using the entity returned by test_insert.
    """
    operation, *_ = ops.get("update")
    query = build_expanded_mutation(sdl_doc, operation)
    assert query, f"Mutation for {operation} not found in SDL"

    # 1) Insert a new entity to update
    entity = await test_insert(sdl_doc, ops, executor)
    variable_values = {**entity}

    assert "id" in entity, f"id not found in insert result {entity}"
    assert "lastchange" in entity, f"lastchange not found in insert result {entity}"

    params = get_mutation_query_params(sdl_doc=sdl_doc, mutation_name=operation)
    for param in params.keys():
        if (param in ["id", "lastchange"]):
            continue
        # 3) Prepare variables by cloning and removing id & lastchange
        variable_values = {
            "id": entity["id"],
            "lastchange": entity["lastchange"],
        }
        if param not in entity:
            continue

        variable_values[param] = entity[param]

        # 2) Execute the update mutation
        result = await executor(query=query, variable_values=variable_values)
        errors = result.get("errors")
        assert errors is None, f"Error during update ({operation}) execution: {errors}"

        # 3) Validate response shape
        data = result.get("data")
        assert data is not None, "Empty response of ({operation}), check resolver for update"
        updated = data.get(operation)
        assert updated is not None, f"Update mutation ({operation}) returned None\n{operation}"
        assert "Error" not in updated.get("__typename", ""), f"{operation} returned error: {updated}"
        assert updated.get("changedbyId", None) is not None, f"{operation} handles changedby by wrong way"

        assert param in updated, f"updated result of ({operation}) has no attribute {param}"        
        assert f"{entity[param]}" == f"{updated[param]}", f"{param} has not been updated check ({operation})"
        entity = updated

        assert "id" in entity, f"id not found in updated result {entity} ({operation}) "
        assert "lastchange" in entity, f"lastchange not found in updated result {entity} ({operation}) "        

    return updated

async def test_delete(sdl_doc, ops, executor):
    """
    Tests the delete mutation for a given type, using the entity returned by test_insert.
    """
    operation, *_ = ops.get("delete")
    query     = build_expanded_mutation(sdl_doc, operation)
    assert query, f"Mutation for {operation} not found in SDL"

    # 1) Insert a new entity so we have something to delete
    entity = await test_insert(sdl_doc, ops, executor)
    variable_values = {**entity}

    # 2) Execute the delete mutation
    result = await executor(query=query, variable_values=variable_values)
    errors = result.get("errors")
    assert errors is None, f"Error during delete execution: {errors}"

    # 3) Validate that the delete field returns None (entity removed)
    data = result.get("data")
    assert data is not None, "Empty response, check resolver for delete"
    deleted = data.get(operation)
    assert deleted is None, f"Expected None after delete, got {deleted}"

    return deleted

def createTests(schema):
    """
    Dynamically generate pytest async tests for all CRUD operations
    based on your federated SDL (_service { sdl }) — no manual schema dict needed.
    """

    import strawberry
    s : strawberry.federation.Schema = schema
    extensions = schema.extensions
    schema.extensions = []

    SERVICE_SDL_QUERY = """
      query {
        _service {
          sdl
        }
      }
    """

    introspection = s.execute_sync(SERVICE_SDL_QUERY)
    schema.extensions = extensions
    # 1) Fetch the federated SDL via the gateway’s _service.sdl field
    
    # executor may be sync or async; detect and call appropriately
    # if asyncio.iscoroutinefunction(executor):
    #     introspection = asyncio.get_event_loop().run_until_complete(
    #         executor(query=SERVICE_SDL_QUERY)
    #     )
    # else:
    #     introspection = executor(query=SERVICE_SDL_QUERY)
    sdl_str = introspection.data["_service"]["sdl"]

    # 2) Parse the SDL string into a DocumentNode
    sdl_doc = parse(sdl_str)

    # 3) Build the CRUD map from the AST
    cruds = get_cruds(sdl_doc)

    # 4) For each type and each op, create a pytest async test
    def create_particular_tests(sdl_doc, typename, optype, ops):
        opmap = {
            "readp": test_page,
            "read": test_scalar,
            "insert": test_insert,
            "update": test_update,
            "delete": test_delete
        }

        def create_particular_test(ops):
            is_resolve = optype not in opmap
            # assert optype in opmap, f"Unknown optype ({optype}) while creating a test"
            test = opmap[optype]

            @pytest.mark.asyncio
            async def test_func(SchemaExecutor):
                if is_resolve:
                    return await createResolveTest(sdl_doc, {typename: []})
                return await test(sdl_doc, ops, SchemaExecutor)
            return test_func



        stored_resolvers = ops.get(optype)
        for resolver in stored_resolvers:
            ops[optype] = [resolver]
            test_func = create_particular_test(ops)
            test_name = f"test_{optype}_{typename}_{resolver}"
            test_func.__name__ = test_name
            
            
            yield test_func

        ops[optype] = stored_resolvers

        pass

    result = {}
    for typename, ops in cruds.items():
        for optype in ("readp", "read", "insert", "update", "delete"):
            if optype not in ops:
                continue
            for test in create_particular_tests(sdl_doc, typename, optype, ops):
                test_name = test.__name__
            
            globals()[test_name] = test
            logging.info(f"Created test {test_name}")
            result[test_name] = test

    @pytest.mark.asyncio
    async def T1():
        return await test_validate_input_descriptions(sdl_doc)

    @pytest.mark.asyncio
    async def T2():
        return await test_validate_object_descriptions(sdl_doc)
    
    @pytest.mark.asyncio
    async def T3():
        return await test_validate_root_descriptions(sdl_doc)
    
    @pytest.mark.asyncio
    async def T4():
        return await test_validate_relation_directives(sdl_doc)
    result["test_input_description"] = T1
    result["test_object_description"] = T2
    result["test_root_description"] = T3
    result["test_validate_relation_directives"] = T4
    return result
        
# async def createResolveTestLocals(sdl_doc: DocumentNode, ops: dict):
#     """
#     Dynamically builds and returns a pytest async test that queries the federated
#     _entities field using representations for each typename/id in `types`.
#     """
#     # 1) Build the _entities query from the SDL AST
#     query = build_entities_query(sdl_doc)
#     logging.info(f"Entities query: {query}")
#     assert query, "Unable to build _entities query from SDL"

#     @pytest.mark.asyncio
#     async def test_entities(SchemaExecutor):
#         await test_scalar(sdl_doc, ops, executor=SchemaExecutor)
#         reps = [
#             {"__typename": tn, "id": str(i)}
#             for tn, ids in types.items() for i in ids
#         ]
#         result = await SchemaExecutor(query=query, variable_values={"representations": reps})
#         errors = result.get("errors")
#         assert errors is None, f"Error during entities execution: {errors}"
#         data = result.get("data")
#         assert data is not None, "Empty response, check federated resolver"
#         entities = data.get("_entities")
#         assert isinstance(entities, list) and entities, "No entities returned"
#         return entities

#     test_entities.__name__ = "test_entities"
#     return test_entities

async def createResolveTest(sdl_doc: DocumentNode, types: dict):
    """
    Dynamically builds and returns a pytest async test that queries the federated
    _entities field using representations for each typename/id in `types`.
    """
    # 1) Build the _entities query from the SDL AST
    query = build_entities_query(sdl_doc)
    logging.info(f"Entities query: {query}")
    assert query, "Unable to build _entities query from SDL"

    @pytest.mark.asyncio
    async def test_entities(SchemaExecutor):
        reps = [
            {"__typename": tn, "id": str(i)}
            for tn, ids in types.items() for i in ids
        ]
        result = await SchemaExecutor(query=query, variable_values={"representations": reps})
        errors = result.get("errors")
        assert errors is None, f"Error during entities execution: {errors}"
        data = result.get("data")
        assert data is not None, "Empty response, check federated resolver"
        entities = data.get("_entities")
        assert isinstance(entities, list) and entities, "No entities returned"
        return entities

    test_entities.__name__ = "test_entities"
    return test_entities


def build_entities_query(sdl_doc: DocumentNode) -> str:
    """
    Builds a federated _entities query selecting all types from the _Entity union.
    Uses build_selection_optional to derive each fragment's selection set.
    """
    # 1) Locate the _Entity union in the AST
    union_def = next(
        (d for d in sdl_doc.definitions
         if isinstance(d, UnionTypeDefinitionNode) and d.name.value == "_Entity"),
        None
    )
    if not union_def or not union_def.types:
        return None

    # 2) For each possible type, build a fragment
    fragments = []
    for named in union_def.types:  # NamedTypeNode
        type_name = named.name.value
        # Build selection for that type
        sel = build_selection_optional(sdl_doc, NamedTypeNode(name=named.name))
        if not sel.strip():
            sel = "{ __typename id }"
        fragments.append(f"... on {type_name} {sel}")

    block = "\n    ".join(fragments)
    return (
        "query($representations: [_Any!]!) {\n"
        "  _entities(representations: $representations) {\n"
        f"    {block}\n"
        "  }\n"
        "}"
    )

def _get_desc(node) -> bool:
    """
    Returns True if the AST node has a non-empty description.
    """
    desc = getattr(node, "description", None)
    return isinstance(desc, StringValueNode) and bool(desc.value.strip())


async def test_validate_input_descriptions(sdl_doc: DocumentNode) -> None:
    """
    Ensures every INPUT_OBJECT and its inputFields has a description.
    Raises ValueError listing missing descriptions.
    """
    errors = []
    for defn in sdl_doc.definitions:
        if isinstance(defn, InputObjectTypeDefinitionNode):
            name = defn.name.value
            if not _get_desc(defn):
                errors.append(f"INPUT type '{name}' is missing a description")
            for field in defn.fields or []:
                if not _get_desc(field):
                    errors.append(f"Input field '{name}.{field.name.value}' is missing a description")
    if errors:
        raise ValueError("Missing descriptions in SDL inputs:\n" + "\n".join(errors))

async def test_validate_object_descriptions(sdl_doc: DocumentNode) -> None:
    """
    Ensures every OBJECT type (excluding Query & Mutation) and its fields has a description.
    Raises ValueError listing missing descriptions.
    """
    errors = []
    for defn in sdl_doc.definitions:
        if isinstance(defn, ObjectTypeDefinitionNode):
            name = defn.name.value
            if name in ("Query", "Mutation"):
                continue
            if name.startswith("_"):
                continue
            if not _get_desc(defn):
                errors.append(f"OBJECT type '{name}' is missing a description")
            for field in defn.fields or []:
                if field.name.value.startswith("_"):
                    continue
                if not _get_desc(field):
                    errors.append(f"Field '{name}.{field.name.value}' is missing a description")
    if errors:
        raise ValueError("Missing descriptions in SDL object types:\n" + "\n".join(errors))

async def test_validate_root_descriptions(sdl_doc: DocumentNode) -> None:
    """
    Ensures Query and Mutation types and all their fields & field args have descriptions.
    Raises ValueError listing missing descriptions.
    """
    errors = []
    for defn in sdl_doc.definitions:
        if isinstance(defn, ObjectTypeDefinitionNode) and defn.name.value in ("Query", "Mutation"):
            typename = defn.name.value
            # if not _get_desc(defn):
            #     errors.append(f"Root type '{typename}' is missing a description")
            for field in defn.fields or []:
                fname = field.name.value
                if fname.startswith('_'):
                    continue
                if not _get_desc(field):
                    errors.append(f"{typename} field '{fname}' is missing a description")
                for arg in field.arguments or []:
                    if not _get_desc(arg):
                        errors.append(f"Argument '{typename}.{fname}({arg.name.value})' is missing a description")
    if errors:
        raise ValueError("Missing descriptions in SDL root types:\n" + "\n".join(errors))
    
async def test_validate_relation_directives(sdl_doc: DocumentNode) -> None:
    """
    Ensure that every field in INPUT_OBJECTs and OBJECTs whose name ends with 'id' or 'Id'
    has a @relation(to: "<TypeName>GQLModel") directive, and that the 'to' argument is
    a string value ending with 'GQLModel'. Raises ValueError listing all violations.
    """
    errors = []

    for defn in sdl_doc.definitions:
        if isinstance(defn, (InputObjectTypeDefinitionNode, ObjectTypeDefinitionNode)):
            type_name = defn.name.value
            if type_name in ["Query", "Mutation"]:
                continue
            for field in defn.fields or []:  # FieldDefinitionNode
                field_name = field.name.value
                if field_name.lower().endswith("id") and field_name != "id":
                    # find @relation directives
                    rel_dirs = [
                        d for d in (field.directives or [])
                        if isinstance(d, DirectiveNode) and d.name.value == "relation"
                    ]
                    if not rel_dirs:
                        errors.append(f"{type_name}.{field_name}: missing @relation directive")
                        continue

                    # there may be multiple, but we check each
                    for d in rel_dirs:
                        # find 'to' argument
                        to_arg = next(
                            (a for a in (d.arguments or []) if isinstance(a, ArgumentNode) and a.name.value == "to"),
                            None
                        )
                        if not to_arg or not isinstance(to_arg.value, StringValueNode):
                            errors.append(
                                f"{type_name}.{field_name}: @relation directive missing string 'to' argument"
                            )
                            continue
                        to_val = to_arg.value.value
                        if not to_val.endswith("GQLModel"):
                            errors.append(
                                f"{type_name}.{field_name}: @relation to='{to_val}' must end with 'GQLModel'"
                            )

    if errors:
        raise ValueError(
            "Relation directive validation errors:\n  " + "\n  ".join(errors)
        )
    

def explain_graphql_query(schema_ast, query):
    from graphql import (
        parse,
        build_ast_schema,
        print_ast
    )
    from graphql.language import DocumentNode, FieldNode
    from graphql.language.visitor import visit
    from graphql.utilities import TypeInfo
    from graphql import parse, build_ast_schema, TypeInfo, visit, GraphQLSchema
    from graphql.language.visitor import visit
    from graphql.language.ast import (
        DocumentNode,
        FieldNode,
        SelectionSetNode,
        OperationDefinitionNode,
    )
    from graphql.type.definition import (
        GraphQLObjectType,
        GraphQLNonNull,
        GraphQLList,
        GraphQLInputObjectType
    )


    schema = build_ast_schema(schema_ast)

    # map description z AST schématu
    field_meta: dict[tuple[str,str], str|None] = {}
    for defn in schema_ast.definitions:
        from graphql.language.ast import ObjectTypeDefinitionNode
        if isinstance(defn, ObjectTypeDefinitionNode):
            parent = defn.name.value
            for fld in defn.fields or []:
                desc = fld.description.value if fld.description else None
                field_meta[(parent, fld.name.value)] = desc
                    


    # parse → AST (DocumentNode)
    query_ast = parse(query)

    # vytisknout strom
    # print(query_ast)
    # nebo jako JSON
    import json
    def node_to_dict(node):
        # graphql-core AST nodes mají `.to_dict()` na Python 3.10+:
        return node.to_dict()

    # print(json.dumps(node_to_dict(query_ast), indent=2))

    # zpět na string
    # print(print_ast(query_ast))

    def unwrap_type(gtype):
        """Strip away NonNull and List wrappers to get the base Named type."""
        while isinstance(gtype, (GraphQLNonNull, GraphQLList)):
            gtype = gtype.of_type
        return gtype

    def type_node_to_str(type_node) -> str:
        """Renders a VariableDefinitionNode.type back to a string."""
        kind = type_node.kind  # e.g. 'NonNullType', 'ListType', or 'NamedType'
        if kind in ["NamedType", "named_type"]:
            return type_node.name.value
        if kind in ["NonNullType", "non_null_type"]:
            return f"{type_node_to_str(type_node.type)}!"
        if kind in ["ListType", "list_type"]:
            return f"[{type_node_to_str(type_node.type)}]"
        raise ValueError(f"Unknown kind {kind}")
    
    def print_query_with_header_comments(query_ast: DocumentNode, schema: GraphQLSchema) -> str:
        # 1) Gather input (variable) descriptions
        var_lines: list[str] = []

        for defn in query_ast.definitions:
            if isinstance(defn, OperationDefinitionNode) and defn.variable_definitions:
                # Předpokládáme, že dotaz obsahuje právě jedno root pole, např. userById
                root_sel = next(
                    (s for s in defn.selection_set.selections if isinstance(s, FieldNode)),
                    None
                )
                if not root_sel:
                    continue

                root_field_name = root_sel.name.value
                # query_type, mutation_type nebo subscription_type dle defn.operation
                root_type_map = {
                    "QUERY":       schema.query_type,
                    "MUTATION":    schema.mutation_type,
                    "subscription": schema.subscription_type
                }
                root_type = root_type_map[defn.operation.name]
                root_field_def = root_type.fields.get(root_field_name)
                # var_lines.append(f"# root args {root_field_def.args}")
                first_arg_name = next(iter(root_field_def.args))  # získá první klíč (jméno argumentu)
                first_arg = root_field_def.args[first_arg_name]  # celý argument (GraphQLArgument)
                first_arg_type = unwrap_type(first_arg.type)
                # var_lines.append(f"# first_arg {first_arg_name}: {first_arg}")
                for var_def in defn.variable_definitions:  # type: VariableDefinitionNode
                    name     = var_def.variable.name.value     # např. "id"
                    type_str = type_node_to_str(var_def.type)  # např. "UUID!"
                    # najdi popis argumentu
                    desc = None
                    if isinstance(first_arg_type, GraphQLInputObjectType):
                        input_fields = first_arg_type.fields  # Dict[str, GraphQLInputField]
                        # Teď můžeš procházet input_fields podle jmen
                        for field_name, input_field in input_fields.items():
                            if field_name != name:
                                continue
                            # print(f"Field: {field_name}, Type: {input_field.type}")
                            desc = input_field.description or "No description"
                            break
                    # if root_field_def and name in root_field_def.args:
                    #     arg_def = root_field_def.args[name]
                    #     desc = arg_def.description
                    # očisti whitespace
                    if desc:
                        desc = " ".join(desc.split())
                        var_lines.append(f"# @param {{{type_str}}} {name} - {desc}")
                    else:
                        var_lines.append(f"# @param {{{type_str}}} {name} - missing description")


        # 2) Gather output (field) descriptions with full dotted path
        out_lines: list[str] = []
        def walk(
            sel_set: SelectionSetNode,
            parent_type: GraphQLObjectType,
            prefix: str
        ):
            for sel in sel_set.selections:
                if not isinstance(sel, FieldNode):
                    continue
                fname = sel.name.value
                path  = f"{prefix}.{fname}" if prefix else fname

                fld_def = parent_type.fields.get(fname)
                if not fld_def:
                    continue

                # unwrap to get the NamedType
                base_type = unwrap_type(fld_def.type)  # GraphQLNamedType
                # fetch the description and normalize whitespace
                desc = field_meta.get((parent_type.name, fname))
                if desc:
                    desc = " ".join(desc.split())
                    # from:
                    # out_lines.append(f'# @property {{""}} {path} - {desc}')
                    # to:
                    out_lines.append(f'# @property {{{base_type.name}}} {path} - {desc}')

                # recurse into nested selections
                if sel.selection_set and isinstance(base_type, GraphQLObjectType):
                    walk(sel.selection_set, base_type, path)

        for defn in query_ast.definitions:
            if isinstance(defn, OperationDefinitionNode):
                # print(f"schema: \n{dir(schema)}")
                root_map = {
                    "QUERY": schema.query_type,
                    "MUTATION": schema.mutation_type,
                    "subscription": schema.subscription_type
                }
                root = root_map[defn.operation.name]
                walk(defn.selection_set, root, prefix="")

        # 3) Build the header block
        header = []
        if var_lines:
            header.append("# ")
            header.extend(var_lines)
        header.append("# @returns {Object}")
        if out_lines:
            header.append("# ")
            header.extend(out_lines)

        # 4) Print the actual query (unmodified) below
        query_str = print_ast(query_ast)

        return "\n".join(header + ["", query_str])  
    
    query_with_header_comments = print_query_with_header_comments(query_ast=query_ast, schema=schema)
    print(f"query_with_header_comments: \n{query_with_header_comments}")
    return query_with_header_comments

class GraphQLQueryBuilder:
    def __init__(self, sdlfilename: str = None, disabled_fields: list[str]=[]):
        # _path = Path(__file__).parent
        # sdl_path =  _path / ("../sdl.graphql" if sdlfilename is None else _path)
        # sdl_path = sdl_path.resolve()
        with open(sdlfilename, "r", encoding="utf-8") as f:
            sdl_lines = f.readlines()
        sdl = "\n".join(sdl_lines)
        directive_text = "directive @key(fields: String!) on OBJECT | INTERFACE"
        sdl = f"{directive_text}\n{sdl}"
        self.ast = parse(sdl)
        # from strawberry.extensions.federation import federation_directives
        # from graphql import GraphQLDirective, DirectiveLocation, GraphQLString

        # federation_directives = [
        #     GraphQLDirective(
        #         name="key",
        #         locations=[DirectiveLocation.OBJECT, DirectiveLocation.INTERFACE],
        #         args={"fields": GraphQLString},
        #         description="Federation @key directive",
        #     ),
        #     # Můžeš přidat další federation direktivy, pokud potřebuješ
        # ]
        # # self.ast.definitions.extend(federation_directives)
        # self.ast.definitions = (*self.ast.definitions, *federation_directives)
        self.schema = build_ast_schema(self.ast) #, assume_valid=True, directives=federation_directives)
        self.adjacency = self._build_adjacency(self.ast, disabled_fields)

    def _unwrap_type(self, t):
        # Unwrap AST type nodes (NonNull, List) to get NamedTypeNode
        while isinstance(t, (NonNullTypeNode, ListTypeNode)):
            t = t.type
        if isinstance(t, NamedTypeNode):
            return t.name.value
        raise TypeError(f"Unexpected type node: {t}")

    def _build_adjacency(self, ast, disabled_fields: list[str]) -> Dict[str, List[Tuple[str, str]]]:
        edges: Dict[str, List[Tuple[str, str]]] = {}
        for defn in ast.definitions:
            if hasattr(defn, 'fields'):
                from_type = defn.name.value
                for field in defn.fields:
                    if field.name.value in disabled_fields:
                        continue
                    to_type = self._unwrap_type(field.type)
                    edges.setdefault(from_type, []).append((field.name.value, to_type))
        return edges

    def _find_path(self, source: str, target: str) -> List[Tuple[str, str]]:
        queue = deque([(source, [])])
        visited = {source}
        while queue:
            current, path = queue.popleft()
            for field, nxt in self.adjacency.get(current, []):
                if nxt == target:
                    return path + [(field, nxt)]
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, path + [(field, nxt)]))
        return []

    def build_query_vector(self, page_operation:str=None, types: List[str]=[]) -> str:
        print(f"building query vector for types {types}")
        root = types[0]
        rootfragment = build_large_fragment(self.ast, root)
        page_operations = get_read_vector_values(self.ast)
        if page_operation is None:
            page_operation = page_operations[root][0]
        # print(f"page_operation {page_operation}")

        field = select_ast_by_path(self.ast, ["Query", page_operation])
        
        # args = [(f"${arg.name.value}: {arg.type.name.value}" + ("!" if isinstance(arg.type, NonNullTypeNode) else "")) for arg in field.arguments]
        args = [f"${arg.name.value}: {self.type_node_to_str(arg.type)}" for arg in field.arguments if field.arguments]
        args_str = ", ".join(args)
        args2 = [(f"{arg.name.value}: ${arg.name.value}") for arg in field.arguments]
        args2_str = ", ".join(args2)
        args3 = [
            (
                f"# ${arg.name.value}: {self.type_node_to_str(arg.type)}" + 
                f" # {arg.description.value if arg.description else ''}"
            )
            for arg in field.arguments
        ]
        args3_str = "\n".join(args3)
        args3_str += "\n\n# to get more results, adjust parameters $skip and / or $limit and call the query until the result is empty vector\n"
        # print(f"args: {args}")

        # print(f"field: {field}, {field.name.value}")
        # Generate fragment definitions for each type
        fragments = [
            build_medium_fragment(self.ast, t)
            for t in types
        ]
        # Precompute full paths from root to each target
        full_paths = {t: self._find_path(root, t) for t in types[1:]}

        def build_spread(current: str, remaining_path: List[Tuple[str, str]]) -> str:
            # If no more path, insert fragment spread
            if not remaining_path:
                return f"...{current}MediumFragment"
            field, next_type = remaining_path[0]
            sub = build_spread(next_type, remaining_path[1:])
            return f"{field} {{ {sub} }}"

        # Build selection sets for each target and combine
        selections = [
            build_spread(root, path)
            for path in full_paths.values()
        ]
        # selections.append(rootfragment)

        unique_selections = list(dict.fromkeys(selections))
        selection_str = "\n   ".join(unique_selections)
        query = f"query {page_operation}({args_str})\n{args3_str}\n{{\n   {page_operation}({args2_str})\n   {{\n    ...{root}MediumFragment\n ...{root}LargeFragment\n    {selection_str} \n   }} \n}}"
        # Append fragments after the main query
        fragments_str = "\n\n".join(fragments)
        result = f"{query}\n\n{fragments_str}\n\n{rootfragment}"
        print(f"vector query \n{result}")
        return result
    
    def type_node_to_str(self, type_node):
        if isinstance(type_node, NonNullTypeNode):
            return self.type_node_to_str(type_node.type) + "!"
        elif isinstance(type_node, ListTypeNode):
            return "[" + self.type_node_to_str(type_node.type) + "]"
        elif isinstance(type_node, NamedTypeNode):
            return type_node.name.value
        else:
            raise TypeError(f"Unknown type node: {type(type_node)}")

    def type_node_to_name(self, type_node):
        if isinstance(type_node, NonNullTypeNode):
            return self.type_node_to_str(type_node.type)
        elif isinstance(type_node, ListTypeNode):
            return self.type_node_to_str(type_node.type)
        elif isinstance(type_node, NamedTypeNode):
            return type_node.name.value
        else:
            raise TypeError(f"Unknown type node: {type(type_node)}")

    def build_query_scalar(self, page_operation:str=None, types: List[str]=[]) -> str:
        
            
        print(f"building query scalar for types {types}")
        root = types[0]
        rootfragment = build_large_fragment(self.ast, root)
        page_operations = get_read_scalar_values(self.ast)
        if page_operation is None:
            page_operation = page_operations[root][0] 
        # print(f"page_operation {page_operation}")

        field = select_ast_by_path(self.ast, ["Query", page_operation])
        if field is None:
            raise ValueError(f"Field {page_operation} not found in Query type")
        # args = [(f"${arg.name.value}: {arg.type.name.value}" + ("!" if isinstance(arg.type, NonNullTypeNode) else "")) for arg in field.arguments]
        args = [f"${arg.name.value}: {self.type_node_to_str(arg.type)}" for arg in field.arguments if field.arguments]
        args_str = ", ".join(args)
        args2 = [(f"{arg.name.value}: ${arg.name.value}") for arg in field.arguments]
        args2_str = ", ".join(args2)
        # print(f"args: {args}")
        args3 = [
            (
                f"# ${arg.name.value}: {self.type_node_to_str(arg.type)}" + 
                f" # {arg.description.value if arg.description else ''}"
            )
            for arg in field.arguments
        ]
        args3_str = "\n".join(args3)

        # print(f"field: {field}, {field.name.value}")
        # Generate fragment definitions for each type
        fragments = [
            build_medium_fragment(self.ast, t)
            for t in types
        ]
        fragments.append(rootfragment)
        # Precompute full paths from root to each target
        full_paths = {t: self._find_path(root, t) for t in types[1:]}

        def build_spread(current: str, remaining_path: List[Tuple[str, str]]) -> str:
            # If no more path, insert fragment spread
            if not remaining_path:
                return f"...{current}MediumFragment"
            field, next_type = remaining_path[0]
            sub = build_spread(next_type, remaining_path[1:])
            return f"{field} {{ {sub} }}"

        # Build selection sets for each target and combine
        selections = [
            build_spread(root, path)
            for path in full_paths.values()
        ]
        unique_selections = list(dict.fromkeys(selections))
        selection_str = " ".join(unique_selections)
        query = f"query {page_operation}({args_str})\n{args3_str}\n{{\n   {page_operation}({args2_str})\n   {{\n    ...{root}MediumFragment\n    ...{root}LargeFragment\n    {selection_str} \n   }} \n}}"
        # Append fragments after the main query
        fragments_str = "\n\n".join(fragments)
        return f"{query}\n\n{fragments_str}"    

