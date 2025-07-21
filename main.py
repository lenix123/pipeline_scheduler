import gitlab
import time
from typing import Dict, List


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
        """Получение списка доступных раннеров для группы"""
        available_runners = []

        return False

    def get_fuzzing_projects(self) -> List[Dict]:
        """Получение списка проектов фаззинга в группе"""
        projects = []

        return projects

     def project_ready(self, project: Dict) -> bool:
        """Проверка, готов ли проект к запуску пайплайна"""
        return project.get('main_branch_exists', False) and project.get('has_gitlab_ci_file', False)

     def get_defect_count(self, project: Dict) -> int:
        """Получение дефектов из Dojo"""
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

        """
        Примерный вариант структуры проекта
        project = {
            'id': int,
            'last_pipeline_run': datetime,
            'last_modified': datetime,
            'pipeline_run_count': int,
            'has_gitlab_ci_file': bool,
            'main_branch_exists': bool,
        }
        """
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
        """Основной метод планирования запусков"""
        # Шаг 1: Проверка доступности ресурсов
        available_runners = self.get_available_runners()
        if not available_runners:
            print("Нет доступных раннеров. Пропуск цикла планирования.")
            return
        
        # Шаг 2: Получение проектов для анализа
        projects = self.get_fuzzing_projects()
        
        # TODO: Реализовать логику приоритезации
        # prioritized_projects = self.prioritize_projects(projects)
        
        # TODO: Реализовать запуск пайплайнов
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