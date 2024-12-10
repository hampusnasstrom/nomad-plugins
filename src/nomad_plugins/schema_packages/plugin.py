from typing import (
    TYPE_CHECKING,
)

from nomad.datamodel.results import ELN, Results

if TYPE_CHECKING:
    from nomad.datamodel.datamodel import (
        EntryArchive,
    )
    from structlog.stdlib import (
        BoundLogger,
    )

import base64
import re

import requests
import toml
from nomad.config import config
from nomad.datamodel.data import ArchiveSection, Author, Schema
from nomad.datamodel.metainfo.annotations import ELNAnnotation, ELNComponentEnum
from nomad.metainfo import Quantity, SchemaPackage, SubSection

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


def get_toml(url: str, subdirectory: str=None, logger: 'BoundLogger'=None) -> dict:
    if subdirectory is None:
        subdir = ''
    else: 
        subdir = f'{subdirectory}/'

    repo_api_url = url.replace(
        'https://github.com',
        'https://api.github.com/repos',
    )
    response = requests.get(f'{repo_api_url}/contents/{subdir}pyproject.toml')
    if response.ok:
        content = response.json().get('content')
        if content:
            toml_content = base64.b64decode(content).decode('utf-8')
            return toml.loads(toml_content)
    elif response.forbidden:
        msg = 'Too many requests to GitHub API. Please try again later.'
        if logger:
            logger.warn(msg)
        else:
            print(msg)
    return {}



class PyprojectAuthor(ArchiveSection):
    name = Quantity(
        type=str,
    )
    email = Quantity(
        type=str,
    )


class Plugin(Schema):
    name = Quantity(
        type=str,
    )
    repository = Quantity(
        type=str,
        a_eln=ELNAnnotation(component=ELNComponentEnum.URLEditQuantity),
    )
    toml_directory = Quantity(
        type=str,
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    description = Quantity(
        type=str,
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
        section=PyprojectAuthor,
        repeats=True,
    )
    maintainers = SubSection(
        section=PyprojectAuthor,
        repeats=True,
    )
    plugin_dependencies = SubSection(
        section='PluginReference',
        repeats=True,
    )

    def find_dependencies(
        self,
        project: dict,
        archive: 'EntryArchive',
        logger: 'BoundLogger'
    ) -> None:
        name_pattern = re.compile(r'^[^;>=<\s]+')
        git_pattern = re.compile(r'@ git\+(.*?)\.git(?:@[^#]+)?(?:#subdirectory=(.*))?')
        self.plugin_dependencies = []
        for dependency in project.get('dependencies', []):
            name = name_pattern.match(dependency).group(0)
            git_match = git_pattern.search(dependency)
            toml_directory = None
            if git_match:
                location = git_match.group(1)
                if git_match.group(2):
                    toml_directory = git_match.group(2)
                project = get_toml(location, toml_directory).get('project', {})
                if not any('nomad-lab' in d for d in project.get('dependencies', [])):
                    continue
            else:
                response = requests.get(f'https://pypi.org/pypi/{name}/json')
                if not response.ok:
                    continue
                response_json = response.json()
                info = response_json.get('info', {})
                dependencies = info.get('requires_dist', [])
                if not dependencies or not any('nomad-lab' in d for d in dependencies):
                    continue
                location = f'https://pypi.org/project/{name}/'

            dep = PluginReference(
                name=name,
                location=location,
                toml_directory=toml_directory,
            )
            dep.normalize(archive, logger)
            self.plugin_dependencies.append(dep)

    def normalize(self, archive: 'EntryArchive', logger: 'BoundLogger') -> None:
        super().normalize(archive, logger)
        if self.repository is None or not self.repository.startswith('https://github.com'):
            return
        pyproject_dict = get_toml(self.repository, self.toml_directory, logger)
        project = pyproject_dict.get('project', {})
        authors = []
        maintainers = []
        for author in project.get('authors', []):
            authors.append(PyprojectAuthor(**author))
        for maintainer in project.get('maintainers', []):
            maintainers.append(PyprojectAuthor(**maintainer))
        self.name = project.get('name', None)
        self.description = project.get('description', None)
        self.authors = authors
        self.maintainers = maintainers
        self.find_dependencies(project, archive, logger)
        if not archive.results:
            archive.results = Results()
        if not archive.results.eln:
            archive.results.eln = ELN()
        archive.results.eln.lab_ids = [self.repository]
        if self.name:
            response = requests.get(f'https://pypi.org/pypi/{self.name}/json')
            if response.ok:
                self.on_pypi = True
                archive.results.eln.lab_ids.append(f'https://pypi.org/project/{self.name}/')


class PluginReference(ArchiveSection):
    name = Quantity(
        type=str,
    )
    location = Quantity(
        type=str,
        a_eln=ELNAnnotation(component=ELNComponentEnum.URLEditQuantity),
    )
    toml_directory = Quantity(
        type=str,
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    plugin = Quantity(
        type=Plugin,
        a_eln=ELNAnnotation(component=ELNComponentEnum.ReferenceEditQuantity),
    )

    def normalize(self, archive: 'EntryArchive', logger: 'BoundLogger') -> None:
        super().normalize(archive, logger)
        from nomad.datamodel.context import ServerContext

        if not isinstance(archive.m_context, ServerContext):
            return
        from nomad.search import MetadataPagination, search
        query = {'results.eln.lab_ids': self.location}
        search_result = search(
            owner='all',
            query=query,
            pagination=MetadataPagination(page_size=1),
            user_id=archive.metadata.main_author.user_id,
        )
        if search_result.pagination.total > 0:
            entry_id = search_result.data[0]['entry_id']
            upload_id = search_result.data[0]['upload_id']
            self.plugin = f'../uploads/{upload_id}/archive/{entry_id}#data'
            if search_result.pagination.total > 1:
                logger.warn(
                    f'Found {search_result.pagination.total} entries with repository: '
                    f'"{self.location}". Will use the first one found.'
                )
        else:
            logger.warn(f'Found no plugins with repository: "{self.location}".')

m_package.__init_metainfo__()
