from setuptools import setup

setup(
    entry_points={
        'console_scripts': [
            'listtypes = uoishelpers.cmds.listtypes:listtypes',
        ],
    },

)
