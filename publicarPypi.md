# Publicar tagsx en PyPI

Primero en TestPyPI, luego en PyPI. La versión vive en `tagsx/__init__.py`.

```bash
rm -rf dist/ build/
uv run pytest
uv build                                    # dist/tagsx-X.Y.Z.tar.gz y .whl

# 1. TestPyPI (cuenta y token en https://test.pypi.org)
uv publish --publish-url https://test.pypi.org/legacy/ --token <token-testpypi>
uv tool run --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ --from tagsx tagsx --version

# 2. PyPI
uv publish --token <token-pypi>
pip install --upgrade tagsx
```

Antes de cada versión: subir `__version__`, añadir la entrada al `CHANGELOG.md` y revisar
que no entra ningún dato de una cuenta real (`git log -p | grep -E '[0-9]{12}'`).
