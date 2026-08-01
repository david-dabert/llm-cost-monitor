from setuptools import setup, find_packages
import os


def read_requirements():
    req_path = os.path.join(os.path.dirname(__file__), "requirements.txt")
    with open(req_path) as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]


def read_long_description():
    readme_path = os.path.join(os.path.dirname(__file__), "README.md")
    with open(readme_path, encoding="utf-8") as f:
        return f.read()


setup(
    name="llm-cost-monitor",
    version="0.1.0",
    description="Transparent proxy and dashboard for tracking LLM API costs in real time",
    long_description=read_long_description(),
    long_description_content_type="text/markdown",
    author="David Dabert",
    author_email="d.dabert89@gmail.com",
    url="https://github.com/david-dabert/llm-cost-monitor",
    license="MIT",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=read_requirements(),
    extras_require={
        "dev": [
            "pytest>=7.0",
            "flake8>=6.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "llm-cost=llm_cost_monitor.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries",
        "Topic :: System :: Monitoring",
    ],
)
