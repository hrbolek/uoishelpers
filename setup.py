from setuptools import setup

setup(
    entry_points={
        'console_scripts': [
            'listtypes = uoishelpers.cmds.listypes:listypes',
        ],
    },

)
