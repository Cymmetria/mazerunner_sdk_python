from setuptools import setup, find_packages

setup(
    name='mazerunner_sdk',
    packages=find_packages(),
    version='1.0.0',
    description='MazeRunner SDK',
    author='Cymmetria',
    author_email='publicapi@cymmetria.com',
    url='https://github.com/Cymmetria/mazerunner_sdk_python',
    download_url='https://github.com/Cymmetria/mazerunner_sdk_python/tarball/1.0.0',
    license='BSD 3-Clause',
    keywords=['cymmetria', 'mazerunner', 'sdk', 'api'],
    install_requires=["requests", "requests-hawk"],
    classifiers=[],
)
