from dataclasses import dataclass

import gitlab
from typing import List, Optional
from datetime import datetime, timedelta
import requests

@dataclass
class ProjectInfo:
    id: int
    name: str
    path_with_namespace: str
    web_url: str
    main_branch_exists: bool
    has_gitlab_ci_file: bool
    last_modified: Optional[datetime]
    last_pipeline_run: Optional[datetime]
    pipeline_run_count: int
    default_branch: str
    archived: bool

class FuzzingPipelineScheduler:
    def __init__(self, gitlab_url: str, private_token: str, group_id: int):
        """
        Инициализация планировщика
        :param gitlab_url: URL GitLab инстанса
        :param private_token: Personal Access Token (права: read_api, read_repository, write_repository)
        :param group_id: ID группы проектов для фаззинга
        """
        self.gl = gitlab.Gitlab(gitlab_url, private_token=private_token)
        self.group_id = group_id
        self.group = self.gl.groups.get(group_id)

        self.weights = {
            'last_change': 0.3,
            'runs_count': 0.2,
            'defects': 0.4
        }

    def get_available_runners(self) -> List[Dict]:
        available_runners = []
        url = f"{self.gitlab_url}/api/v4/groups/{self.group_id}/runners"
        page = 1

        while True:
            response = requests.get(url, headers=self.headers, params={'per_page': 100, 'page': page})
            if response.status_code != 200:
                raise Exception(f"GitLab API error: {response.status_code} - {response.text}")

            data = response.json()
            if not data:
                break

            available_runners.extend(data)
            page += 1

        return available_runners

    def get_fuzzing_projects(self) -> List[ProjectInfo]:
        result: List[ProjectInfo] = []
        group = self.gl.groups.get(self.group_id, lazy=True)
        all_projects = group.projects.list(include_subgroups=True, all=True)

        for project_stub in all_projects:
            try:
                project = self.gl.projects.get(project_stub.id)
                default_branch = project.default_branch or "main"
                main_branch_exists = True
                has_gitlab_ci_file = False
                last_modified = None
                last_pipeline_run = None
                pipeline_run_count = 0

                # Проверка существования ветки
                try:
                    project.branches.get("main")
                except gitlab.exceptions.GitlabGetError:
                    main_branch_exists = False

                # Проверка наличия .gitlab-ci.yml
                if main_branch_exists:
                    try:
                        project.files.get(file_path=".gitlab-ci.yml", ref="main")
                        has_gitlab_ci_file = True
                    except gitlab.exceptions.GitlabGetError:
                        pass

                # Получение времени последнего коммита в main
                if main_branch_exists:
                    commits = project.commits.list(ref_name="main", per_page=1)
                    if commits:
                        last_modified = datetime.strptime(commits[0].committed_date, "%Y-%m-%dT%H:%M:%S.%f%z")

                # Получение pipeline'ов
                if main_branch_exists:
                    pipelines = project.pipelines.list(ref="main", order_by="updated_at", sort="desc", per_page=1)
                    pipeline_run_count = project.pipelines.list(ref="main", per_page=1).pagination['total'] \
                        if hasattr(project.pipelines.list(ref="main", per_page=1), 'pagination') else 0

                    if pipelines:
                        last_pipeline_run = datetime.strptime(pipelines[0].updated_at, "%Y-%m-%dT%H:%M:%S.%f%z")

                result.append(ProjectInfo(
                    id=project.id,
                    name=project.name,
                    path_with_namespace=project.path_with_namespace,
                    web_url=project.web_url,
                    main_branch_exists=main_branch_exists,
                    has_gitlab_ci_file=has_gitlab_ci_file,
                    last_modified=last_modified,
                    last_pipeline_run=last_pipeline_run,
                    pipeline_run_count=pipeline_run_count,
                    default_branch=default_branch,
                    archived=project.archived
                ))

            except gitlab.exceptions.GitlabGetError:
                continue

        return result

    def project_ready(self, project: ProjectInfo) -> bool:
        """Проверка, готов ли проект к запуску пайплайна"""
        return project.main_branch_exists and project.has_gitlab_ci_file

    def get_defect_count(self, project: Dict) -> int:
        """
        Получение количества открытых дефектов из DefectDojo для проекта.
        Выполняется только если настроен API токен DefectDojo.
        """
        if not self.defectdojo_url or not self.defectdojo_token:
            # Пропускаем, если не задана интеграция
            return 0 
    
        try:
            headers = {
                'Authorization': f'Token {self.defectdojo_token}',
                'Content-Type': 'application/json',
            }
    
            search_url = f"{self.defectdojo_url}/api/v2/products/?name={project['name']}"
            response = requests.get(search_url, headers=headers, timeout=5)
            response.raise_for_status()
    
            products = response.json().get('results', [])
            
            if not products:
                return 0
    
            product_id = products[0]['id']
    
            findings_url = f"{self.defectdojo_url}/api/v2/findings/?product={product_id}&active=true&verified=true&false_p=false&duplicate=false"
            findings_response = requests.get(findings_url, headers=headers, timeout=5)
            findings_response.raise_for_status()
    
            findings = findings_response.json().get('results', [])
            return len(findings)
    
        except requests.RequestException as e:
            print(f"[WARN] Не удалось получить данные из DefectDojo для проекта {project['name']}: {e}")
            return 0

    def normalize(self, values: List[float]) -> List[float]:
        """Нормализация значений от 0 до 1"""
        if not values:
            return []
        min_v, max_v = min(values), max(values)
        if min_v == max_v:
            return [0.5 for _ in values]
        return [(v - min_v) / (max_v - min_v) for v in values]
        
    def prioritize_projects(self, projects):
        now = datetime.utcnow()
        filtered_projects = []
        last_changes = []
        run_counts = []
        defect_counts = []

        # Фильтрация и сбор данных
        for p in projects:
            if not self.project_ready(p):
                continue

            if p.last_pipeline_run and now - p.last_pipeline_run < timedelta(hours=24):
                continue

            defect_count = self.get_defect_count(p)

            filtered_projects.append(p)
            last_changes.append((now - p.last_modified).total_seconds())
            run_counts.append(p.pipeline_run_count)
            defect_counts.append(defect_count)

        if not filtered_projects:
            return []

        # Нормализация: чем выше значение — тем выше приоритет
        norm_last_change = self.normalize(last_changes)
        norm_runs_count = [1 - x for x in self.normalize(run_counts)]  # меньше запусков — выше приоритет 
        norm_defects = self.normalize(defect_counts)

        # Расчет итогового приоритета
        scored_projects = []
        for i, p in enumerate(filtered_projects):
            score = (
                norm_last_change[i] * self.weights['last_change'] +
                norm_runs_count[i] * self.weights['runs_count'] +
                norm_defects[i] * self.weights['defects']
            )
            scored_projects.append((score, p))

        # Сортировка по убыванию приоритета
        scored_projects.sort(reverse=True, key=lambda x: x[0])
        return [p for _, p in scored_projects]


    def schedule_pipelines(self) -> None:
        print("Планирование запусков пайплайнов...")

        # Шаг 1: Проверка доступности раннеров
        available_runners = self.get_available_runners()
        if not available_runners:
            print("Нет доступных раннеров. Пропуск цикла планирования.")
            return

        # Шаг 2: Получение проектов
        projects = self.get_fuzzing_projects()
        if not projects:
            print("Нет доступных проектов в группе.")
            return

        # Шаг 3: Приоритезация проектов
        prioritized_projects = self.prioritize_projects(projects)
        if not prioritized_projects:
            print("Нет проектов, удовлетворяющих условиям для запуска.")
            return

        # Шаг 4: Запуск пайплайнов
        # self.run_pipelines(prioritized_projects, available_runners)

        print("Планирование завершено (логика приоритезации будет реализована в следующей версии)")

if __name__ == "__main__":
    GITLAB_URL = "https://gitlab.example.com"
    PRIVATE_TOKEN = "your_glpat_token"
    GROUP_ID = 123  # ID фаззинг группы
    
    scheduler = FuzzingPipelineScheduler(
        gitlab_url=GITLAB_URL,
        private_token=PRIVATE_TOKEN,
        group_id=GROUP_ID
    )
    
    # Запуск планировщика
    scheduler.schedule_pipelines()