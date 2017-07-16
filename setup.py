from setuptools import setup, find_packages

setup(
    name='mazerunner_sdk',
    packages=find_packages(),
    version='1.1.4',
    description='MazeRunner SDK',
    author='Cymmetria',
    author_email='publicapi@cymmetria.com',
    url='https://github.com/Cymmetria/mazerunner_sdk_python',
    download_url='https://github.com/Cymmetria/mazerunner_sdk_python/tarball/1.1.4',
    license='BSD 3-Clause',
    keywords=['cymmetria', 'mazerunner', 'sdk', 'api'],
    install_requires=["argparse==1.2.1",
                      "mohawk==0.3.4",
                      "requests==2.13.0",
                      "requests-hawk==1.0.0",
                      "six==1.10.0",
                      "wsgiref==0.1.2"],
    classifiers=[],
)
