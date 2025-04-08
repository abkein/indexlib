#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2024 Perevoshchikov Egor
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

import shutil
import tarfile
from pathlib import Path


def copy_items_iterative(src_path: Path, dest_path: Path, max_size_bytes: int) -> None:
    stack = [(src_path, dest_path)]
    while stack:
        current_src, current_dest = stack.pop()
        for item in current_src.iterdir():
            dest_item = current_dest / item.name
            if item.is_dir():
                dest_item.mkdir(parents=True, exist_ok=True)
                stack.append((item, dest_item))
            elif item.is_file():
                try:
                    if max_size_bytes == 0:
                        shutil.copy2(item, dest_item)
                    else:
                        if item.stat().st_size <= max_size_bytes:
                            shutil.copy2(item, dest_item)
                        else:
                            print(f"Skipping file (size exceeds {max_size_bytes}B): {item}")
                except OSError as e:
                    print(f"Error copying file {item}: {e}")


def copy_and_compress_folder_lzma(src_folder: Path, dest_folder: Path, max_size_bytes: int, delete_uncompressed: bool = True) -> Path:
    """
    Recursively copy a folder to a new location, including hidden files and directories,
    excluding files bigger than max_size_mb. Then compress the copied folder into a .tar.xz
    archive using LZMA compression and delete the uncompressed copy.

    Parameters:
    src_folder (str or Path): The path to the source folder.
    dest_folder (str or Path): The path to the destination folder.
    max_size_bytes (int): The maximum file size to copy.

    Returns:
    Path: The path to the compressed archive.
    """

    if not src_folder.exists():
        raise FileNotFoundError(f"Source folder '{src_folder}' does not exist.")

    if dest_folder.exists():
        raise RuntimeError("Destination folder exists")

    dest_folder.mkdir(parents=True, exist_ok=True)
    copy_items_iterative(src_folder, dest_folder, max_size_bytes)

    archive_name = dest_folder.with_suffix('.tar.xz')
    with tarfile.open(archive_name, 'w:xz') as tar:
        tar.add(dest_folder, arcname=dest_folder.name)

    if delete_uncompressed:
        shutil.rmtree(dest_folder)

    print(f"Folder compressed into archive: {archive_name}")
    return archive_name


if __name__ == "__main__":
    pass
