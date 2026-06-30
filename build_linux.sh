#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

APP_NAME="DailyTodo"
APP_VERSION="${1:-0.0.0}"
BUILD_TYPE="${2:-dev}"
case "$BUILD_TYPE" in
    development|debug)
        BUILD_TYPE="dev"
        ;;
    prod|production)
        BUILD_TYPE="release"
        ;;
esac
case "$BUILD_TYPE" in
    dev|release)
        ;;
    *)
        echo "Usage: $0 [version] [dev|release]" >&2
        exit 2
        ;;
esac
PYTHON=".venv/bin/python"
PIP=".venv/bin/pip"
DEPLOY=".venv/bin/pyside6-deploy"
DIST_DIR="dist"
APP_DIST="deployment/main.dist"
PACKAGE_ROOT="$DIST_DIR/package"
PACKAGE_DIR="$PACKAGE_ROOT/$APP_NAME"
TAR_PATH="$DIST_DIR/$APP_NAME-$APP_VERSION-$BUILD_TYPE-linux.tar.gz"

if [ ! -x "$PYTHON" ]; then
    echo "[DailyTodo] Creating virtual environment..."
    python3 -m venv .venv
fi

echo "[DailyTodo] Installing dependencies..."
"$PIP" install -r requirements.txt

echo "[DailyTodo] Building translations..."
"$PYTHON" tools/build_translations.py

echo "[DailyTodo] Writing pyside6-deploy spec for $BUILD_TYPE $APP_VERSION..."
"$PYTHON" tools/write_deploy_spec.py --version "$APP_VERSION" --build-type "$BUILD_TYPE"

echo "[DailyTodo] Building Linux standalone directory with pyside6-deploy..."
"$DEPLOY" -c pysidedeploy.spec --name "$APP_NAME" --force --keep-deployment-files

if [ ! -d "$APP_DIST" ]; then
    echo "[DailyTodo] Build output not found: $APP_DIST" >&2
    exit 1
fi

mkdir -p "$DIST_DIR"
rm -rf "$PACKAGE_ROOT"
mkdir -p "$PACKAGE_DIR"
cp -a "$APP_DIST"/. "$PACKAGE_DIR"/
rm -f "$TAR_PATH"

echo "[DailyTodo] Creating tar.gz package: $TAR_PATH"
tar -czf "$TAR_PATH" -C "$PACKAGE_ROOT" "$APP_NAME"

echo "[DailyTodo] Linux package completed: $TAR_PATH"
echo "[DailyTodo] Run executable from extracted package: ./DailyTodo/main"
