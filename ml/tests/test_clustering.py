import numpy as np

from ml.clustering import cluster_average, cluster_components, pair_scores


def block_matrix():
    # два плотных блока {0,1,2} и {3,4}; между ними слабая связь 0.5 через пару (2,3)
    P = np.zeros((5, 5))
    for grp in ([0, 1, 2], [3, 4]):
        for i in grp:
            for j in grp:
                P[i, j] = 0.95
    P[2, 3] = P[3, 2] = 0.5
    np.fill_diagonal(P, 1.0)
    return P


def same_partition(labels, groups):
    return all(len({labels[i] for i in g}) == 1 for g in groups) and len(set(labels)) == len(groups)


def test_components_and_average_split_blocks():
    P = block_matrix()
    assert same_partition(cluster_components(P, 0.9), [[0, 1, 2], [3, 4]])
    assert same_partition(cluster_average(P, 0.9), [[0, 1, 2], [3, 4]])


def test_chaining_difference():
    P = block_matrix()
    assert len(set(cluster_components(P, 0.4))) == 1      # одно слабое ребро склеивает всё
    assert len(set(cluster_average(P, 0.8))) == 2         # средняя связь не склеивает


def test_pair_scores_perfect_and_merged():
    truth = np.array([0, 0, 1, 1])
    assert pair_scores(truth, np.array([5, 5, 7, 7]))["f1"] == 1.0
    merged = pair_scores(truth, np.array([0, 0, 0, 0]))
    assert merged["recall"] == 1.0 and merged["precision"] < 1.0


def test_single_item():
    assert list(cluster_average(np.ones((1, 1)), 0.5)) == [0]
