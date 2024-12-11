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

    from nomad_plugins.schema_packages import PluginSchemaPackageEntryPoint

import base64
import datetime
import re

import requests
import toml
from nomad.config import config
from nomad.datamodel.data import ArchiveSection, Author, Schema
from nomad.datamodel.metainfo.annotations import ELNAnnotation, ELNComponentEnum
from nomad.metainfo import Datetime, Quantity, SchemaPackage, SubSection

configuration: 'PluginSchemaPackageEntryPoint' = config.get_plugin_entry_point(
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
    headers = {}
    if configuration.github_api_token:
        headers={
            'Authorization': f'token {configuration.github_api_token}'
        }
    response = requests.get(
        f'{repo_api_url}/contents/{subdir}pyproject.toml',
        headers=headers,
    )
    if response.ok:
        content = response.json().get('content')
        if content:
            toml_content = base64.b64decode(content).decode('utf-8')
            return toml.loads(toml_content)
    elif response.status_code == requests.codes.forbidden:
        msg = 'Too many requests to GitHub API. Please try again later.'
        if logger:
            logger.warn(msg)
        else:
            print(msg)
    else:
        msg = (
            f'Failed to get pyproject.toml from {url}: '
            f'{response.json().get("message", "No message")}'
        )
        if logger:
            logger.warn(msg)
        else:
            print(msg)
    return None


def on_gitlab_oasis(
        plugin_name: str,
        oasis_toml: str,
        logger: 'BoundLogger'=None) -> bool:
    response = requests.get(oasis_toml)
    if not response.ok:
        msg = f'Failed to get pyproject.toml from {oasis_toml}: {response.text}'
        if logger:
            logger.warn(msg)
        else:
            print(msg)
    pyproject_data = toml.loads(response.text)
    name_pattern = re.compile(r'^[^;>=<\s]+')
    plugin_dependencies = pyproject_data['project']['optional-dependencies']['plugins']
    return plugin_name in [name_pattern.match(d).group() for d in plugin_dependencies]


class PyprojectAuthor(ArchiveSection):
    name = Quantity(
        type=str,
    )
    email = Quantity(
        type=str,
    )


class Plugin(Schema):
    repository = Quantity(
        type=str,
        a_eln=ELNAnnotation(component=ELNComponentEnum.URLEditQuantity),
    )
    toml_directory = Quantity(
        type=str,
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    created = Quantity(
        type=Datetime,
        a_eln=ELNAnnotation(component=ELNComponentEnum.DateTimeEditQuantity),
    )
    name = Quantity(
        type=str,
    )
    description = Quantity(
        type=str,
    )
    owner = Quantity(
        type=str,
    )
    on_pypi = Quantity(
        type=bool,
        default=False,
    )
    on_central = Quantity(
        type=bool,
    )
    on_example_oasis = Quantity(
        type=bool,
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
        if not archive.results:
            archive.results = Results()
        if not archive.results.eln:
            archive.results.eln = ELN()
        archive.results.eln.lab_ids = [self.repository]
        if self.created is None:
            self.created = datetime.datetime.now()
        if self.repository is None:
            return
        match = re.match(r'https://github.com/([^/]+)/([^/]+)', self.repository)
        if not match:
            logger.warn(f'Invalid repository URL: {self.repository}')
        self.owner = match.group(1)
        pyproject_dict = get_toml(self.repository, self.toml_directory, logger)
        if pyproject_dict is None:
            return
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
        if self.name:
            response = requests.get(f'https://pypi.org/pypi/{self.name}/json')
            if response.ok:
                self.on_pypi = True
                archive.results.eln.lab_ids.append(f'https://pypi.org/project/{self.name}/')
        if self.on_central is None:
            self.on_central = on_gitlab_oasis(
                self.name,
                'https://gitlab.mpcdf.mpg.de/nomad-lab/nomad-distro/-/raw/main/pyproject.toml'
            )
        if self.on_example_oasis is None:
            self.on_example_oasis = on_gitlab_oasis(
                self.name,
                'https://gitlab.mpcdf.mpg.de/nomad-lab/nomad-distro/-/raw/test-oasis/pyproject.toml'
            )


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
