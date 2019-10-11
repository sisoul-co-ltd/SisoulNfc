from setuptools import setup

setup(
    name='SisoulNfc',
    version='0.6.0',
    packages=['pysisoulnfc'],
    url='http://sisoul.co.kr',
    license='Commercial',
    author='Kim Youngseon',
    author_email='sean.kim@sisoul.co.kr',
    description='Sisoul NFC SDK for SMCP-IV',
    python_requires='>=3.5',
    install_requires=['Cython', 'hidapi', 'pyftdi', 'multipledispatch'],
    keywords=['nfc'],
    zip_safe=False,
    classifiers=[
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6'
    ]
)
