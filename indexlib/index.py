#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2023-2024 Perevoshchikov Egor
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

# Last modified: 25-10-2024 04:05:43

from __future__ import annotations

import os
import sys
import json
import argparse
import warnings
from enum import Enum
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from abc import abstractmethod
from typing import Literal, Union, Generator, Any

import argcomplete
from marshmallow import Schema, fields, post_load


def is_subpath_to(path: Path, to: Path) -> bool:
    if path == to:
        return False
    try:
        path.relative_to(to)
        return True
    except ValueError:
        return False


ignore_list: list[Path] = []


class FieldPath(fields.Field):
    def _deserialize(self, value: str, attr, data, **kwargs) -> Path:
        return Path(value).resolve(True)

    def _serialize(self, value: Path, attr, obj, **kwargs) -> str:
        return value.as_posix()


class PathEntityProtocolSchema(Schema):
    type = fields.Constant('PathEntityProtocol')
    path = FieldPath()
    category = fields.Integer()
    is_directory = fields.Boolean()
    info = fields.String(allow_none=True, missing=None)


class PathEntityProtocol:
    path: Path
    category: int
    is_directory: bool
    parent: 'DirectoryEntity'
    info: Union[str, None]

    def __init__(self, path: Path, category: int, parent: DirectoryEntity, is_directory: Union[bool, None] = None, info: Union[str, None] = None) -> None:
        self.path = path
        self.category = category
        if is_directory is not None:
            self.is_directory = is_directory
        elif self.path.exists():
            self.is_directory = self.path.is_dir()
        else:
            raise RuntimeError("Cannot get path type: is_directory is None and path does not exists.")
        self.parent = parent
        self.info = info

    @abstractmethod
    def delete_self(self, unregister: bool = False, recursive: bool = True) -> None: ...

    def set_parent(self, parent: DirectoryEntity) -> None:
        self.parent = parent

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def unregister_self(self, recursive: bool = True) -> None:
        if self.path in ignore_list:
            warnings.warn(f"Unregister self method called on path in ignore-list: {self.path.as_posix()} — ignoring", RuntimeWarning)
            return
        self.parent.unregister(self, recursive)


class CategorySchema(Schema):
    name = fields.String()
    info = fields.String(allow_none=True, missing=None)

    @post_load
    def make_object(self, data: dict[str, Any], *args, **kwargs):
        return Category(**data)


class Category:
    name: str
    info: Union[str, None]
    members: list[PathEntityProtocol] = []

    def __init__(self, name: str, info: Union[str, None]) -> None:
        super().__init__()
        self.name = name
        self.info = info
        self.members = []

    def add(self, element: PathEntityProtocol) -> None:
        self.members.append(element)

    def remove(self, entity: Union[Path, PathEntityProtocol]) -> None:
        path: Path
        if isinstance(entity, Path):
            path = entity
        elif isinstance(entity, PathEntityProtocol):
            path = entity.path

        for instance in self.members:
            if path == instance.path:
                self.members.remove(instance)
                return

        raise RuntimeError("Member wasn't found")

    def clear(self):
        self.members = []

    def delete(self, unregister: bool = False, clear: bool = False, recursive: bool = True):
        for mem in self.members:
            mem.delete_self()
            if unregister:
                mem.unregister_self(recursive)
        if clear:
            self.clear()

    def unregister_members(self, recursive: bool = True) -> None:
        for instance in reversed(self.members):
            instance.unregister_self(recursive)
            self.members.remove(instance)

    @property
    def elements(self) -> int:
        return len(self.members)


class FileEntity(PathEntityProtocol):
    is_directory: bool = False

    def __init__(self, path: Path, category: int, parent: DirectoryEntity, info: Union[str, None] = None) -> None:
        super().__init__(path, category, parent, False, info)

    def delete_self(self, unregister: bool = False, recursive: bool = True) -> None:
        if self.path in ignore_list:
            warnings.warn(f"Delete self method called on path in ignore-list: {self.path.as_posix()} — ignoring", RuntimeWarning)
            return
        if self.exists:
            self.path.unlink(True)
        if unregister:
            self.unregister_self(recursive)


class FileEntitySchema(Schema):
    type = fields.Constant('FileEntity')
    path = FieldPath()
    category = fields.Integer()
    info = fields.String(allow_none=True, missing=None)

    @post_load
    def make_object(self, data: dict[str, Any], *args, **kwargs):
        _p = self.context.get("parent")
        if not isinstance(_p, (DirectoryEntity, Index)):
            raise RuntimeError(f"Provided parent object is invalid. Type: {type(_p)}")

        instance = FileEntity.__new__(FileEntity)
        instance.path = data["path"]
        instance.category = data["category"]
        instance.is_directory = False
        instance.parent = _p
        instance.info = data["info"]
        return instance


def rm_contents(folder: Path) -> None:
    if not folder.is_dir():
        raise RuntimeError(f"Specified path is not directory: {folder.as_posix()}")

    folders: list[Path] = []

    for item in folder.iterdir():
        if item.is_dir():
            folders.append(item)
        else:
            if item in ignore_list:
                warnings.warn(f"Attempt to delete path in ignore-list: {item.as_posix()} — ignoring", RuntimeWarning)
                continue
            item.unlink(True)

    for fldr in folders:
        rm_contents(fldr)
        fldr.rmdir()


class PolyField(fields.Field):
    def _deserialize(self, value: dict[str, Any], attr: str | None, data: dict[str, Any] | None, **kwargs):
        type_ = value.pop('type')

        schema = self._get_schema(type_=type_)
        assert isinstance(self.root, Schema)
        return schema.load(value, unknown=self.root.unknown)

    def _serialize(self, value: DirectoryEntity | FileEntity, attr: str | None, obj: Any, **kwargs):
        schema = self._get_schema(obj=value)
        return schema.dump(value)

    def _get_schema(self, type_: str | None = None, obj: DirectoryEntity | FileEntity | None = None) -> DirectoryEntitySchema | FileEntitySchema:
        # Determine the schema class based on type or object
        if type_ is not None:
            schema_class = self._get_schema_class_by_type(type_)
        elif obj is not None:
            schema_class = self._get_schema_class_by_object(obj)
        else:
            raise ValueError("Either 'type_' or 'obj' must be provided")

        # Create an instance of the schema, propagating context and other attributes
        return self._make_schema_instance(schema_class)

    def _get_schema_class_by_type(self, type_: str) -> type[FileEntitySchema] | type[DirectoryEntitySchema]:
        if type_ == 'FileEntity':
            return FileEntitySchema
        elif type_ == 'DirectoryEntity':
            return DirectoryEntitySchema
        else:
            raise ValueError(f"Unknown type: {type_}")

    def _get_schema_class_by_object(self, obj: FileEntity | DirectoryEntity) -> type[FileEntitySchema] | type[DirectoryEntitySchema]:
        if isinstance(obj, FileEntity):
            return FileEntitySchema
        elif isinstance(obj, DirectoryEntity):
            return DirectoryEntitySchema
        else:
            raise ValueError(f"Unknown type: {type(obj)}")

    def _make_schema_instance(self, schema_class: type[FileEntitySchema] | type[DirectoryEntitySchema]) -> DirectoryEntitySchema | FileEntitySchema:
        parent = self.parent
        root = self.root

        # Get attributes from the parent or root schema
        context = getattr(root, 'context', {})
        partial = getattr(root, 'partial', False)
        unknown = getattr(root, 'unknown', None)

        # Create the schema instance with the propagated attributes
        schema = schema_class(
            context=context,
            partial=partial,
            unknown=unknown
        )

        return schema


class DirectoryEntitySchema(Schema):
    type = fields.Constant('DirectoryEntity')
    path = FieldPath()
    category = fields.Integer()
    info = fields.String(allow_none=True, missing=None)
    childs = fields.List(PolyField(), missing=[])

    @post_load
    def make_object(self, data: dict[str, Any], *args, **kwargs):
        _p = self.context.get("parent")
        if not isinstance(_p, (DirectoryEntity, Index)):
            raise RuntimeError(f"Provided parent object is invalid. Type: {type(_p)}")

        instance = DirectoryEntity.__new__(DirectoryEntity)
        instance.path = data["path"]
        instance.category = data["category"]
        instance.is_directory = True
        instance.parent = _p
        instance.info = data["info"]
        instance.childs = data["childs"]

        return instance


class RE(Enum):
    REGISTERED = 0
    UNREGISTERED = 1
    UNREGISTERED_DEEP = 2
    ALL = 3


def get_path(elem: Path | PathEntityProtocol) -> Path:
    if isinstance(elem, Path):
        return elem
    else:
        return elem.path


class DirectoryEntity(PathEntityProtocol):
    is_directory: bool = True
    childs: list[PathEntityProtocol]
    __temp_root: Index | None = None

    def __init__(self, path: Path, category: int, parent: DirectoryEntity, info: Union[str, None] = None) -> None:
        super().__init__(path, category, parent, True, info)
        self.childs = []

    def unregister_all(self) -> None:
        self.__temp_root = self.get_root()
        savelist: list[PathEntityProtocol] = []
        for child in self.childs:
            if isinstance(child, DirectoryEntity):
                child.unregister_all()
            if child.path in ignore_list:
                savelist.append(child)
            self.get_root().get_category(child.category).remove(child)

        self.childs = savelist
        self.__temp_root = None

    def __delete_registered(self, unregister: bool = False) -> None:
        for child in self.childs:
            if child.path in ignore_list:
                continue
            child.delete_self()
        if unregister:
            self.unregister_all()

    def __delete_unregistered(self, deep: bool) -> None:
        cont = list(self.path.iterdir())
        for child in self.childs:
            if isinstance(child, DirectoryEntity):
                if deep:
                    child.delete_specific(RE.UNREGISTERED_DEEP)
                cont.remove(child.path)
        for path in cont:
            if not self.isregistered(path):
                if path.is_dir():
                    rm_contents(path)
                    path.rmdir()
                else:
                    path.unlink()

    def __delete_all(self, unregister: bool = False):
        rm_contents(self.path)
        if unregister:
            self.unregister_all()

    def delete_specific(self, method: RE, unregister: bool = False) -> None:
        if method == RE.ALL:
            self.__delete_all(unregister)
        elif method == RE.REGISTERED:
            self.__delete_registered(unregister)
        elif method == RE.UNREGISTERED:
            self.__delete_unregistered(False)
        elif method == RE.UNREGISTERED_DEEP:
            self.__delete_unregistered(True)
        else:
            raise NotImplementedError(f"Unknown 'method' passed: {method}")

    def delete_self(self, unregister: bool = False, recursive: bool = True) -> None:
        if self.path in ignore_list:
            warnings.warn(f"Attempt to delete path in ignore-list: {self.path.as_posix()} — ignoring", RuntimeWarning)
            return
        self.delete_specific(RE.ALL, unregister)
        if self.exists:
            self.path.rmdir()
        if unregister:
            self.unregister_self(recursive)

    def get_root(self) -> Index:
        if self.__temp_root is not None:
            return self.__temp_root
        if self.parent is self:
            raise RuntimeError("Infinite loop: parent==self detected")
        return self.parent.get_root()

    def issub(self, sub: Union[Path, PathEntityProtocol]) -> bool:
        return is_subpath_to(get_path(sub), self.path)

    def __check4sub(self, sub: Path | PathEntityProtocol):
        if not self.issub(sub):
            raise ValueError(f"Passed child is not subpath: {self.path.as_posix()} vs {get_path(sub).as_posix()}")

    def deepest_parent(self, sub: Path | PathEntityProtocol) -> DirectoryEntity:
        self.__check4sub(sub)
        for child in self.childs:
            if isinstance(child, DirectoryEntity) and child.issub(sub):
                return child.deepest_parent(sub)
        return self

    def __register(self, sub: PathEntityProtocol):
        self.__check4sub(sub)
        for child in self.childs:
            if child.path == sub.path:
                raise RuntimeError(f"Path {sub.path.as_posix()} already registered")
        self.childs.append(sub)
        sub.set_parent(self)
        self.get_root().get_category(sub.category).add(sub)

    def register(self, sub: PathEntityProtocol) -> None:
        self.__check4sub(sub)
        if self.isregistered(sub):
            raise RuntimeError(f"Path {sub.path.as_posix()} already registered")
        parent = self.deepest_parent(sub)
        parent.__register(sub)

    def __unregister(self, sub: Path | PathEntityProtocol, recursive: bool = True) -> None:
        self.__check4sub(sub)
        if get_path(sub) in ignore_list:
            return
        el = self.find(sub)

        if isinstance(el, DirectoryEntity) and not recursive:
            for elem in el.childs:
                elem.set_parent(self)
                self.childs.append(elem)

        self.get_root().get_category(el.category).remove(el)
        self.childs.remove(el)

    def unregister(self, sub: Path | PathEntityProtocol, recursive: bool = True) -> None:
        self.__check4sub(sub)
        parent = self.deepest_parent(sub)
        parent.__unregister(sub, recursive)

    def __isregistered(self, sub: Path | PathEntityProtocol) -> bool:
        self.__check4sub(sub)
        path = get_path(sub)
        for child in self.childs:
            if path == child.path:
                return True
        return False

    def isregistered(self, entity: Union[Path, PathEntityProtocol]) -> bool:
        parent = self.deepest_parent(entity)
        return parent.__isregistered(entity)

    def __find(self, sub: Path | PathEntityProtocol) -> PathEntityProtocol:
        self.__check4sub(sub)
        path = get_path(sub)
        for child in self.childs:
            if path == child.path:
                return child

        raise RuntimeError("Child wasn't found")

    def find(self, sub: Path | PathEntityProtocol) -> PathEntityProtocol:
        self.__check4sub(sub)
        parent = self.deepest_parent(sub)
        return parent.__find(sub)

    def adoption(self) -> None:
        for child in self.childs:
            child.set_parent(self)
            if isinstance(child, DirectoryEntity):
                child.adoption()

    def walk(self) -> Generator[PathEntityProtocol, None, None]:
        for obj in self.childs:
            yield obj
            if isinstance(obj, DirectoryEntity):
                yield obj
                for _obj in obj.walk():
                    yield _obj


def walk_system(path: Path) -> Generator[Path, Path, None]:
    if path.is_file():
        return
    for obj in path.iterdir():
        yield obj
        if obj.is_dir():
            for _obj in walk_system(obj):
                yield _obj


_default_filename: str = '.index.json'


class Index(DirectoryEntity):
    created: datetime
    _categories: list[Category]
    __dbfile: Path

    def __from_db(self):
        with self.__dbfile.open('r') as fp:
            idx = IndexSchema(context={"parent": self}).load(json.load(fp))
            if not isinstance(idx, Index):
                raise RuntimeError("Invalid index, seems corrupted")
            self.created = idx.created
            self._categories = idx._categories
            self.childs = idx.childs
            self.parent = self

    def commit(self):
        with self.__dbfile.open('w') as fp:
            json.dump(IndexSchema().dump(self), fp, indent=4)

    def __init__(self, cwd: Path = Path.cwd()) -> None:
        super().__init__(cwd, -1, self, "Root")
        self.__dbfile = cwd / _default_filename
        if self.__dbfile.exists():
            return self.__from_db()

        timezone_str = os.environ.get('TZ', 'UTC')
        self.created = datetime.now(ZoneInfo(timezone_str))

        _ = Category('root', "Root folder category")
        self._categories = [Category('default', "Default category")]
        self.register(self.__dbfile, "default", False, "Index database file")

    def get_root(self):
        return self

    def find_category(self, _category: Union[str, int]) -> tuple[Literal[True], int, Category] | tuple[Literal[False], Literal[-1], None]:
        if isinstance(_category, int):
            try:
                category = self._categories[_category]
                return True, _category, category
            except IndexError:
                return False, -1, None
        elif isinstance(_category, str):
            for i, category in enumerate(self._categories):
                if _category == category.name:
                    return True, i, category
            return False, -1, None
        else:
            raise RuntimeError("Category must be one of: str, int")

    def get_category(self, category: int) -> Category:
        return self._categories[category]

    def register_category(self, category_name: str, info: Union[str, None] = None) -> None:
        found, *_ = self.find_category(category_name)
        if found: raise RuntimeError(f"Category '{category_name}' already exists")
        self._categories.append(Category(category_name, info))

    def unregister_category(self, _category: Union[str, int], unregister_members: bool = False, recursive: bool = True) -> None:
        found, _, category = self.find_category(_category)
        if not found: raise RuntimeError(f"Category '{_category}' does not exists")
        assert isinstance(category, Category)

        if category.elements > 0:
            if not unregister_members:
                raise RuntimeError("Category is not empty")
            else:
                category.unregister_members(recursive)

        self._categories.remove(category)

    def register(self, path: Path, _category: Union[str, int], is_directory: Union[bool, None] = None, info: Union[str, None] = None) -> None:
        found, idx, _ = self.find_category(_category)
        if not found:
            raise RuntimeError(f"Category '{_category}' does not exists")

        child: PathEntityProtocol
        if is_directory is None:
            if path.exists():
                is_directory = path.is_dir()
            else:
                raise RuntimeError("Cannot get path type: is_directory is None and path does not exists.")
        if is_directory:
            child = DirectoryEntity(path, idx, self, info)
        else:
            child = FileEntity(path, idx, self, info)

        super().register(child)

    def delete_category(self, category: str | int, unregister: bool = False, clear: bool = False, recursive: bool = True):
        found, _, cat  = self.find_category(category)
        if not found:
            raise ValueError("Category was not found")
        assert cat is not None
        cat.delete(unregister, clear, recursive)

    def delete(self, sub: Path, unregister: bool = False, recursive: bool = True):
        child = self.find(sub)
        child.delete_self(unregister, recursive)


class IndexSchema(Schema):
    path = FieldPath()
    created = fields.DateTime()
    categories = fields.List(fields.Nested(CategorySchema), attribute="_categories", data_key="categories")
    childs = fields.List(PolyField(), missing=[])

    @post_load
    def make_object(self, data: dict[str, Any], **kwargs):
        instance = Index.__new__(Index)
        instance.path = data["path"]
        instance.category = -1
        instance.is_directory = True
        instance.parent = instance
        instance.info = "Root"
        instance.childs = data["childs"]

        instance.created = data["created"]
        instance._categories = data["_categories"]
        instance.adoption()
        for obj in instance.walk():
            instance._categories[obj.category].add(obj)
        return instance


def main() -> int:
    parser_main = argparse.ArgumentParser('index', description="Directory indexing tool", add_help=True)

    subs_main = parser_main.add_subparsers(dest="command")

    ### REGISTER
    parser_register = subs_main.add_parser('register', help='Register an entry')
    subs_register = parser_register.add_subparsers(dest="kind", required=True)

    parser_register_category = subs_register.add_parser("category", help="Register a category")
    parser_register_category.add_argument("name", action="store", type=str, help="Category name")
    parser_register_category.add_argument("--info", "-i", action="store", type=str, help="Category info", default=None)

    parser_register_path = subs_register.add_parser("path", help=f"Register a path")
    parser_register_path.add_argument("--type", "-t", choices=["directory", "file"], type=str, help="Path type")
    parser_register_path.add_argument("path", action="store", type=str, help="Path to register")
    parser_register_path.add_argument("--info", "-i", action="store", type=str, help="Path info", default=None)
    parser_register_path.add_argument("--category", "-c", action="store", type=str, help="Path category", default="default")

    parser_register_file = subs_register.add_parser("file", help=f"Register a file")
    parser_register_file.add_argument("path", action="store", type=str, help="File to register")
    parser_register_file.add_argument("--info", "-i", action="store", type=str, help="File info", default=None)
    parser_register_file.add_argument("--category", "-c", action="store", type=str, help="File category", default="default")

    parser_register_directory = subs_register.add_parser("directory", aliases=["dir", "folder", "fldr"], help=f"Register a directory")
    parser_register_directory.add_argument("path", action="store", type=str, help="Directory to register")
    parser_register_directory.add_argument("--info", "-i", action="store", type=str, help="Directory info", default=None)
    parser_register_directory.add_argument("--category", "-c", action="store", type=str, help="Directory category", default="default")

    ### UNREGISTER
    parser_unregister = subs_main.add_parser('unregister', help='Unregister an entry')
    subs_unregister = parser_unregister.add_subparsers(dest="kind", required=True)

    parser_unregister_category = subs_unregister.add_parser("category", help="Register a category")
    parser_unregister_category.add_argument("name", action="store", type=str, help="Category name")
    parser_unregister_category.add_argument("--with-members", "-wm", action="store_true", help="Unregister category members", dest="wm")
    parser_unregister_category.add_argument("--non-recursive", "-nr", action="store_false", help="Unregister only members (without its childs)", dest="nr")

    parser_unregister_path = subs_unregister.add_parser("path", help=f"Unregister a path")
    parser_unregister_path.add_argument("--non-recursive", "-nr", action="store_false", help="Unregister only this forlder (without its childs)", dest="nr")
    parser_unregister_path.add_argument("path", action="store", type=str, help="Path to unregister")

    ### DELETE
    parser_delete = subs_main.add_parser('delete', help='Delete an entry')
    subs_delete = parser_delete.add_subparsers(dest="kind", required=True)

    parser_delete_category = subs_delete.add_parser("category", help="Delete a category members")
    parser_delete_category.add_argument("name", action="store", type=str, help="Category name")
    parser_delete_category.add_argument("--clear", "-c", action="store_true", help="Clear category")
    parser_delete_category.add_argument("--unregister", "-u", action="store_true", help="Unregister its members")
    parser_delete_category.add_argument("--non-recursive", "-nr", action="store_false", help="Unregister only this forlder (without its childs)", dest="nr")

    parser_delete_path = subs_delete.add_parser("path", help=f"Deletes a path, not unregisters it. Actually does 'rm -rf'")
    parser_delete_path.add_argument("path", action="store", type=str, help="Path to delete")
    parser_delete_path.add_argument("--unregister", "-u", action="store_true", help="Do unregsiter")
    parser_delete_path.add_argument("--non-recursive", "-nr", action="store_false", help="Unregister only this forlder (without its childs)", dest="nr")

    parser_delete_registered = subs_delete.add_parser("registered", help="Delete registered pathes")
    parser_delete_registered.add_argument("--unregister", "-u", action="store_true", help="Do unregsiter")

    parser_delete_unregistered = subs_delete.add_parser("unregistered", help="Delete unregistered pathes")
    parser_delete_unregistered.add_argument("--deep", "-d", action="store_true", help="Delete unregistered files under registered directories")

    parser_delete_all = subs_delete.add_parser("all", help="Delete all. Actually does 'rm -rf .'")

    argcomplete.autocomplete(parser_main)

    args = parser_main.parse_args()

    index = Index()

    t = True
    if args.command == 'register':
        if args.kind == 'category':
            index.register_category(args.name, args.info)
        else:
            _pth = Path(args.path).resolve()
            if args.kind == "directory" or args.kind == "dir":
                index.register(_pth, args.category, True, args.info)
            elif args.kind == "file":
                index.register(_pth, args.category, False, args.info)
            elif args.kind == "path":
                index.register(_pth, args.category, args.type != "file", args.info)
            else:
                raise ValueError("Unknown kind to register")
    elif args.command == "unregister":
        if args.kind == "category":
            index.unregister_category(args.name, args.wm, args.nr)
        elif args.kind == "path":
            index.unregister(Path(args.path).resolve(), args.recursuve)
        else:
            raise ValueError("Unknown kind to register")
    elif args.command == "delete":
        if args.kind == 'category':
            index.delete_category(args.name, args.unregister, args.clear, args.nr)
        elif args.kind == "path":
            _pth = Path(args.path).resolve()
            index.delete(_pth, args.unregister, args.nr)
        elif args.kind == "registered":
            index.delete_specific(RE.REGISTERED, args.unregister)
        elif args.kind == "unregistered":
            index.delete_specific(RE.UNREGISTERED_DEEP if args.deep else RE.UNREGISTERED)
        elif args.kind == "all":
            index.delete_specific(RE.ALL)
        else:
            raise ValueError("Unknown kind to register")
    else:
        t = False

    if t:
        index.commit()

    return 0


if __name__ == "__main__":
    sys.exit(main())
