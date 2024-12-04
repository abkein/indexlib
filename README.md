# IndexLib

IndexLib is a Python package designed to provide a comprehensive directory indexing tool. It allows developers to register, unregister, and manage directories and files efficiently. The package is particularly useful for organizing and maintaining large file systems.

## Features

- **Register and Unregister**: Easily register and unregister files and directories.
- **Category Management**: Organize files and directories into categories for better management.
- **Deletion**: Supports deletion of registered and unregistered paths, with options for recursive operations.
- **Serialization**: Uses Marshmallow for serialization and deserialization of file and directory entities.
- **Command Line Interface**: Provides a CLI for easy interaction with the indexing tool.

## Installation

To install IndexLib, ensure you have Python 3.11 or higher, and run the following command:

```bash
pip install indexlib
```

## Usage

IndexLib can be used both as a library in your Python code and as a command-line tool.

### As a Library

```python
from indexlib import Index

# Initialize the index
index = Index()

# Register a directory
index.register_category('my_category', 'A custom category for my files')
index.register('/path/to/directory', 'my_category')

# Commit changes
index.commit()
```

### Command Line Interface

```bash
# Register a directory
index register directory /path/to/directory --category my_category

# Unregister a directory
index unregister path /path/to/directory

# Delete a category
index delete category my_category --unregister
```

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request for any improvements or bug fixes.

## License

IndexLib is licensed under the MIT License. See the LICENSE file for more details.

## Contact

For any questions or issues, please open an issue on the [GitHub repository](https://github.com/abkein/indexlib/issues).
