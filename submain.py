import argparse
import datetime
import numpy as np
import os
import pickle
import random
import socket
import sys
import time

from activetm.active import evaluate
from activetm.active import select
from activetm import models
from activetm import utils

def partition_data_ids(num_docs, rng, settings):
    TEST_SIZE = int(settings['testsize'])
    START_LABELED = int(settings['startlabeled'])
    shuffled_doc_ids = list(range(num_docs))
    rng.shuffle(shuffled_doc_ids)
    test_doc_ids = list(shuffled_doc_ids[:TEST_SIZE])
    labeled_doc_ids = list(shuffled_doc_ids[TEST_SIZE:TEST_SIZE+START_LABELED])
    unlabeled_doc_ids = set(shuffled_doc_ids[TEST_SIZE+START_LABELED:])
    return test_doc_ids, labeled_doc_ids, unlabeled_doc_ids

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Job runner for ActiveTM '
            'experiments')
    parser.add_argument('working_dir', help='ActiveTM directory '
            'available to hosts (should be a network path)')
    parser.add_argument('settings', help=\
            '''the path to a file containing settings, as described in \
            README.md in the root ActiveTM directory''')
    parser.add_argument('outputdir', help='directory for output')
    parser.add_argument('label', help='identifying label')
    args = parser.parse_args()

    settings = utils.parse_settings(args.settings)
    trueoutputdir = os.path.join(args.outputdir, settings['group'])
    if not os.path.exists(trueoutputdir):
        try:
            os.makedirs(trueoutputdir)
        except OSError:
            pass
    filename = socket.gethostname()+'.'+str(os.getpid())
    runningfile = os.path.join(args.outputdir, 'running',
            filename)
    try:
        with open(runningfile, 'w') as outputfh:
            outputfh.write('running')

        start = time.time()
        input_pickle = os.path.join(args.outputdir, utils.get_pickle_name(args.settings))
        with open(input_pickle, 'rb') as ifh:
            dataset = pickle.load(ifh)
        rng = random.Random(int(settings['seed']))
        model = models.build(rng, settings)
        test_doc_ids, labeled_doc_ids, unlabeled_doc_ids =\
                partition_data_ids(dataset.num_docs, rng, settings)
        test_labels = []
        test_words = []
        for t in test_doc_ids:
            test_labels.append(dataset.labels[dataset.titles[t]])
            test_words.append(dataset.doc_tokens(t))
        test_labels_mean = np.mean(test_labels)
        known_labels = []
        for t in labeled_doc_ids:
            known_labels.append(dataset.labels[dataset.titles[t]])

        SELECT_METHOD = select.factory[settings['select']]
        END_LABELED = int(settings['endlabeled'])
        LABEL_INCREMENT = int(settings['increment'])
        CAND_SIZE = int(settings['candsize'])
        results = []
        end = time.time()
        init_time = datetime.timedelta(seconds=end-start)

        start = time.time()
        select_and_train_start = time.time()
        model.train(dataset, labeled_doc_ids, known_labels)
        select_and_train_end = time.time()
        metric = evaluate.pR2(model, test_words, test_labels,
                test_labels_mean)
        results.append([len(labeled_doc_ids),
                datetime.timedelta(seconds=time.time()-start).total_seconds(),
                datetime.timedelta(seconds=select_and_train_end-select_and_train_start).total_seconds(),
                metric])
        while len(labeled_doc_ids) < END_LABELED and len(unlabeled_doc_ids) > 0:
            select_and_train_start = time.time()
            # must make unlabeled_doc_ids (which is a set) into a list
            candidates = select.reservoir(list(unlabeled_doc_ids), rng, CAND_SIZE)
            chosen = SELECT_METHOD(dataset, labeled_doc_ids, candidates, model,
                    rng, LABEL_INCREMENT)
            for c in chosen:
                known_labels.append(dataset.labels[dataset.titles[c]])
                labeled_doc_ids.append(c)
                unlabeled_doc_ids.remove(c)
            model.train(dataset, labeled_doc_ids, known_labels, True)
            select_and_train_end = time.time()
            metric = evaluate.pR2(model, test_words, test_labels,
                    test_labels_mean)
            results.append([len(labeled_doc_ids),
                    datetime.timedelta(seconds=time.time()-start).total_seconds(),
                    datetime.timedelta(seconds=select_and_train_end-select_and_train_start).total_seconds(),
                    metric])
        model.cleanup()

        output = []
        output.append('# init time: {:s}'.format(str(init_time)))
        for result in results:
            output.append('\t'.join([str(r) for r in result]))
        output.append('')
        with open(os.path.join(trueoutputdir, args.label), 'w') as ofh:
            ofh.write('\n'.join(output))
    finally:
        os.remove(runningfile)

