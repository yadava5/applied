#!/bin/bash
# =============================================================================
# JobTracker Installation Script
# =============================================================================
# One-command setup for the JobTracker backend.
#
# Usage:
#   ./scripts/install.sh
#
# What it does:
#   1. Creates Python virtual environment
#   2. Installs PyTorch CPU-only
#   3. Installs all dependencies
#   4. Downloads ML models
#   5. Initializes database
# =============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored message
print_step() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}!${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
BACKEND_DIR="$PROJECT_ROOT/backend"

echo ""
echo "=============================================="
echo "   JobTracker Backend Installation"
echo "=============================================="
echo ""

# Check prerequisites
print_step "Checking prerequisites..."

# Check Python version
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 not found. Please install Python 3.11+"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
REQUIRED_VERSION="3.11"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    print_error "Python $REQUIRED_VERSION+ required, found $PYTHON_VERSION"
    exit 1
fi

print_success "Python $PYTHON_VERSION found"

# Navigate to backend directory
cd "$BACKEND_DIR"

# Create virtual environment
print_step "Creating virtual environment..."

if [ -d ".venv" ]; then
    print_warning "Virtual environment already exists, skipping..."
else
    python3 -m venv .venv
    print_success "Virtual environment created"
fi

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip
print_step "Upgrading pip..."
pip install --upgrade pip -q
print_success "pip upgraded"

# Install PyTorch CPU-only
print_step "Installing PyTorch (CPU-only)..."
pip install torch --index-url https://download.pytorch.org/whl/cpu -q
print_success "PyTorch installed"

# Install dependencies
print_step "Installing dependencies..."
pip install -r requirements.txt -q
print_success "Dependencies installed"

# Install dev dependencies (optional)
read -p "Install development dependencies? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_step "Installing development dependencies..."
    pip install -r requirements-dev.txt -q
    print_success "Development dependencies installed"
fi

# Download ML models
print_step "Downloading ML models (this may take a minute)..."
python3 -c "
from sentence_transformers import SentenceTransformer
print('  Downloading e5-small-v2 model...')
SentenceTransformer('intfloat/e5-small-v2')
print('  Model downloaded successfully')
"
print_success "ML models downloaded"

# Initialize database
print_step "Initializing database..."
python3 -m jobtracker.database.init
print_success "Database initialized"

# Verify installation
print_step "Verifying installation..."

# Try to import main module
python3 -c "from jobtracker.main import app; print('  FastAPI app imports successfully')"
print_success "Installation verified"

echo ""
echo "=============================================="
echo "   Installation Complete!"
echo "=============================================="
echo ""
echo "To start the backend server:"
echo ""
echo "  ./scripts/start_backend.sh"
echo ""
echo "Then open http://127.0.0.1:8000/docs for API documentation"
echo ""
