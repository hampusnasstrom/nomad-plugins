from typing import (
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from nomad.datamodel.datamodel import (
        EntryArchive,
    )
    from structlog.stdlib import (
        BoundLogger,
    )

import requests
from nomad.config import config
from nomad.datamodel.data import ArchiveSection, Author, Schema
from nomad.datamodel.metainfo.annotations import ELNAnnotation, ELNComponentEnum
from nomad.metainfo import Quantity, SchemaPackage, SubSection
import base64
import toml

configuration = config.get_plugin_entry_point(
    'nomad_plugins.schema_packages:schema_package_entry_point'
)

m_package = SchemaPackage()


def nomad_author(author: dict[str, str]) -> Author:
    name_parts = author.get('name', '').split()
    first_name = ' '.join(name_parts[:-1]) if name_parts else ''
    last_name = name_parts[-1] if len(name_parts) > 1 else ''
    return Author(
        first_name=first_name,
        last_name=last_name,
        email=author.get('email', '')
    )


class Plugin(Schema):
    name = Quantity(
        type=str, 
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    repository = Quantity(
        type=str,
        a_eln=ELNAnnotation(component=ELNComponentEnum.URLEditQuantity),
    )
    description = Quantity(
        type=str,
        a_eln=ELNAnnotation(component=ELNComponentEnum.RichTextEditQuantity),
    )
    on_pypi = Quantity(
        type=bool,
        default=False,
    )
    on_central = Quantity(
        type=bool,
        default=False,
    )
    on_example_oasis = Quantity(
        type=bool,
        default=False,
    )
    authors = SubSection(
        section=Author,
        repeats=True,
    )
    maintainers = SubSection(
        section=Author,
        repeats=True,
    )
    plugin_dependencies = SubSection(
        section='PluginReference',
        repeats=True,
    )

    def normalize(self, archive: 'EntryArchive', logger: 'BoundLogger') -> None:
        super().normalize(archive, logger)
        if self.repository and self.repository.startswith('https://github.com'):
            repo_api_url = self.repository.replace(
                'https://github.com',
                'https://api.github.com/repos',
            )
            response = requests.get(f'{repo_api_url}/contents/pyproject.toml')
            if response.ok:
                pyproject_content = response.json().get('content')
                if pyproject_content:
                    pyproject_toml = base64.b64decode(pyproject_content).decode('utf-8')
                    pyproject_dict = toml.loads(pyproject_toml)
                    project = pyproject_dict.get('project', {})
                    authors = []
                    maintainers = []
                    for author in project.get('authors', []):
                        authors.append(nomad_author(author))
                    for maintainer in project.get('maintainers', []):
                        maintainers.append(nomad_author(maintainer))
                    if self.name is None:
                        self.name = project.get('name', None)
                    if self.description is None:
                        self.description = project.get('description', None)
                    self.authors = authors
                    self.maintainers = maintainers
                    for dependency in project.get('dependencies', []):
                        self.plugin_dependencies.append(PluginReference(name=dependency))
        if self.name:
            response = requests.get(f'https://pypi.org/pypi/{self.name}/json')
            if response.ok:
                self.on_pypi = True


class PluginReference(ArchiveSection):
    name = Quantity(
        type=str,
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    plugin = Quantity(
        type=Plugin,
        a_eln=ELNAnnotation(component=ELNComponentEnum.ReferenceEditQuantity),
    )

    def normalize(self, archive: 'EntryArchive', logger: 'BoundLogger') -> None:
        super().normalize(archive, logger)

m_package.__init_metainfo__()
