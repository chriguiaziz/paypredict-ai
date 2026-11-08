"""Tests du générateur de données synthétiques.

Un test automatique (pytest) vérifie une promesse du code. Si quelqu'un casse le
générateur plus tard, ces tests le détectent tout de suite.
Pytest exécute toute fonction dont le nom commence par `test_`.
"""
import pytest   # le framework de tests

from ml.data_generator import dataset_hash, generate_all   # le code à tester
from ml.validate_data import run_checks                    # les 20 contrôles qualité


@pytest.fixture(scope="module")
def frames():
    """Prépare les données une seule fois pour tous les tests de ce fichier.

    Une 'fixture' est une préparation partagée. scope="module" veut dire qu'on
    génère les 4 tables une fois seulement (c'est long), pas avant chaque test.
    """
    return generate_all(seed=42)


def test_reproducibility(frames):
    """Même graine => jeu de données strictement identique."""
    # On régénère avec la même graine 42 et on compare les empreintes (hash).
    assert dataset_hash(frames) == dataset_hash(generate_all(seed=42))


def test_different_seed_changes_data(frames):
    """Graine différente => données différentes (le hasard dépend bien de la graine)."""
    assert dataset_hash(frames) != dataset_hash(generate_all(seed=7))


def test_all_quality_checks_pass(frames):
    """Les 20 contrôles qualité de validate_data.py doivent tous réussir."""
    results = run_checks(frames["customers"], frames["invoices"],
                         frames["payments"], frames["ground_truth"])
    # Chaque résultat est (nom, réussi ?, détail) : r[1] vaut False en cas d'échec.
    failures = [r for r in results if not r[1]]
    # Si la liste n'est pas vide, le test échoue et affiche les contrôles ratés.
    assert not failures, failures