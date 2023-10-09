#!/usr/bin/env python
# =============================================================================
# Pimmi CLI Endpoint
# =============================================================================
#
# CLI enpoint of the Pimmi library.

import os
import csv
import sys
import shutil
import logging
import argparse
import os
import glob
import pimmi.toolbox as tbx
import pimmi.pimmi_parameters as constants
from pimmi.clusters import generate_clusters, from_clusters_to_viz
from pimmi.eval import evaluate
from pimmi.cli.config import parameters as prm
from pimmi import load_index, save_index, fill_index_mt, create_index_mt, get_index_images, query_index_mt
from pathlib import Path
import math

logger = logging.getLogger("pimmi")
parser = argparse.ArgumentParser(prog="pimmi", description='PIMMI: a command line tool for image mining.')
config_path = os.path.join(os.path.dirname(__file__), "config.yml")
config_dict = prm.load_config_file(config_path)
for param, value in config_dict.items():
    if type(value) == dict and "help" in value:
        help_message = value["help"]
        default = value["value"]
        argument_type = type(value["value"])
    else:
        help_message = argparse.SUPPRESS
        argument_type = type(value)
        default = value

    parser.add_argument(
        "--{}".format(param.replace("_", "-")),
        type=argument_type,
        default=default,
        help=help_message
    )


def load_cli_parameters():
    subparsers = parser.add_subparsers(title="commands")

    # FILL command
    parser_fill = subparsers.add_parser('fill', help="Create index and fill with vectors of images. Receive IMAGE-DIR, "
                                                     "a directory containing images. Index these images and save. "
                                                     "INDEX-NAME will be used as index id by other pimmi commands.")

    parser_fill.add_argument('image_dir', type=str, metavar='image-dir')
    parser_fill.add_argument('index_dir', type=str,  help="Directory where the index should be stored/loaded. ")

    #parser_fill.add_argument("--index-path", type=str, help="Directory where the index should be stored/loaded from. "
     #                                                       "Defaults to './index'", default="./index")
    parser_fill.add_argument("-e", "--erase", action="store_true", help="Erase previously existing index "
                                                                        "if there is one. By default, do not erase and"
                                                                        "fill the existing index with new "
                                                                        "images.")
    parser_fill.add_argument("-f", "--force", action="store_true", help="Avoid confirmation prompt if the index already"
                                                                        "exists.")
    parser_fill.add_argument("--config-path", type=str, help="Path to custom config file. Use 'pimmi create-config' to "
                                                             "create a config file template.")
    parser_fill.add_argument("-n", "--nb-img", type=int, help="Use only the first n images in `image_dir`")
    parser_fill.set_defaults(func=fill)

    # QUERY command
    parser_query = subparsers.add_parser('query', help="Query an existing index. Receive IMAGE-DIR, a directory "
                                                       "containing images, and INDEX-NAME, the name given to the index "
                                                       "when using `pimmi fill`.")
    parser_query.add_argument('image_dir', type=str, metavar='image-dir')
    parser_query.add_argument('index_dir', type=str, help="Directory where the index should be loaded from. ")
    parser_query.add_argument("-o", "--output", type=argparse.FileType('w'), default=sys.stdout, help="Path to output file. If not provided, print to stdout.")
    parser_query.add_argument("--output-template", type=str, help='If the filename template is fou, the filenames will be fou1.csv, fou2.csv ...')
    parser_query.add_argument("--nb-per-split", type=int, default=10000, help="Number of images to query per pack.")
    parser_query.add_argument("--nb-per-files", type=int, help="Number of images to query per files."
                                 " Requires to indicate a --filename-template ")
    parser_query.add_argument("--config-path", type=str, help="Path to custom config file. Use 'pimmi create-config' to"
                                                              " create a config file template.")
    parser_query.add_argument("--simple", action="store_true", default=False)
    parser_query.add_argument("-n", "--nb-img", type=int, help="Query only the first n images in `image_dir`")
    parser_query.set_defaults(func=query)

    # CLUSTERS command
    clusters_query = subparsers.add_parser('clusters', help="Create clusters from query results.")
    clusters_query.add_argument('index_dir', type=str, help="Directory where the index should be loaded from. ")
    clusters_query.add_argument('filename', nargs='?', type=str, default=sys.stdin,
                                help="File or file template where the data from query should be loaded from. ")

    clusters_query.add_argument("--config-path", type=str, help="Path to custom config file. Use 'pimmi create-config' to"
                                                              " create a config file template.")
    clusters_query.add_argument("--algo", type=str, default='components',
                                help="'components' or 'louvain'. Defaults to 'components'")
    clusters_query.add_argument("-o", "--output", type=argparse.FileType('w'), default=sys.stdout,
                                help="Path to output file. If not provided, print to stdout.")
    clusters_query.set_defaults(func=clusters)

    # VIZ command
    parser_viz = subparsers.add_parser('viz', help="Create an input file for the visualisation tool pimmi ui. Receive a CSV file containing the clusters.")
    parser_viz.add_argument('clusters', nargs='?', type=argparse.FileType('r'), default=sys.stdin)
    parser_viz.add_argument("-o", "--output", type=argparse.FileType('w'), default=sys.stdout,
                            help="Path to output file. If not provided, print to stdout.")
    parser_viz.set_defaults(func=viz)

    # EVAL command
    parser_eval = subparsers.add_parser('eval', help="Evaluate quality of clusters")
    parser_eval.add_argument("file", type=str, metavar="file")
    parser_eval.add_argument("--predicted-column", type=str, default="predicted", help="Name of the column containing predicted clusters.")
    parser_eval.add_argument("--truth-column", type=str, default="truth", help="Name of the column containing ground truth.")
    parser_eval.add_argument("--query-column", type=str, help="If you want to compute average query precision, " \
        "name of the column containing 'original' for each query image.")
    parser_eval.add_argument("--ignore-missing", action="store_true", help="Ignore rows where no cluster has been predicted.")
    parser_eval.add_argument("--csv", action="store_true", help="Format output as csv row.")

    parser_eval.set_defaults(func=eval)

    # CONFIG-PARAMS command
    parser_config_params = subparsers.add_parser('config-params',
                                                 help="List all arguments that can be passed to pimmi to "
                                                      "override the standard configuration file.")
    parser_config_params.set_defaults(func=config_params)

    # CREATE-CONFIG command
    parser_create_config = subparsers.add_parser('create-config', help="Create a custom config file. Usage: 'pimmi "
                                                                       "create-config my_config_file.yml'")
    parser_create_config.add_argument('path', type=str, help="Path of the file to be created.")
    parser_create_config.set_defaults(func=create_config)

    cli_parameters = vars(parser.parse_args(namespace=prm))
    return cli_parameters


def fill(image_dir, index_dir, nb_img, erase=False, force=False, **kwargs):
    if not os.path.isdir(image_dir):
        logger.error("The provided image-dir is not a directory.")
        sys.exit(1)

    if not os.path.isdir(Path(index_dir).parent):
        print('Please enter a valid directory')
        index_dir = input()
        if not os.path.isdir(Path(index_dir).parent):
            logger.error("{} does not exist.".format(os.path.abspath(index_dir)))
            sys.exit(1)
        else:
            faiss_index, faiss_meta = index_dir+"/index.faiss", index_dir+"/index.meta"
            if os.path.isfile(faiss_index) and os.path.isfile(faiss_meta):
                index_exists = True
                if not force:
                    if erase:
                        if not confirm("Are you sure that you want to erase the previously existing index in the folder"+str(Path(index_dir).parent)+"?"):
                            logger.error("Please restart pimmi fill without '--erase/-e'.")
                            sys.exit(1)
                    else:
                        if not confirm(
                                "The index already exists. Do you want to fill it with additional images?"
                        ):
                            #todo: change the term directory
                            logger.error("Please restart pimmi fill with '--erase' or choose another directory.")
                            sys.exit(1)
            else:
                os.mkdir(index_dir)
                index_exists = False
    else:
        #faiss_index, faiss_meta = make_index_path(index_dir, index_name, prm.index_type)
        faiss_index, faiss_meta = index_dir+"/index.faiss", index_dir+"/index.meta"
        if os.path.isfile(faiss_index) and os.path.isfile(faiss_meta):
            index_exists = True
            if not force:
                if erase:
                    if not confirm("Are you sure that you want to erase the previously existing index in the folder"+str(Path(index_dir).parent)+"?"):
                        logger.error("Please restart pimmi fill without '--erase/-e'.")
                        sys.exit(1)
                else:
                    if not confirm(
                            "The index already exists. Do you want to fill it with additional images?"
                    ):
                        #todo: change the term directory
                        logger.error("Please restart pimmi fill with '--erase' or choose another directory.")
                        sys.exit(1)
        else:
            os.mkdir(index_dir)
            index_exists = False
        #todo: error if one file exists but not the other

    logger.info("listing images recursively from : " + image_dir)
    images = tbx.get_all_images(image_dir, nb_img)

    sift = tbx.Sift(prm.sift_nfeatures, prm.sift_nOctaveLayers, prm.sift_contrastThreshold, prm.sift_edgeThreshold,
                    prm.sift_sigma, prm.nb_threads)

    if erase or not index_exists:
        filled_index = create_index_mt(prm.index_type, images, image_dir, sift, verbose=not prm.silent)
    else:
        previous_index = load_index(faiss_index, faiss_meta)
        filled_index = fill_index_mt(previous_index, images, image_dir, sift)

    save_index(filled_index, faiss_index, faiss_meta)


def query( image_dir, index_dir,output, nb_per_split,nb_per_files, output_template, simple, nb_img, **kwargs):
    faiss_index, faiss_meta = index_dir+"/index.faiss", index_dir+"/index.meta"

    index = load_index(faiss_index, faiss_meta)

    images = get_index_images(index, image_dir, nb_img)

    if simple:
        prm.query_dist_filter = False
        prm.query_adaptative_sift_knn = False

    logger.info("total number of queries " + str(len(images)))
    # images = images.sort_values(by=constants.dff_image_path)
    images.sort(key=lambda x: x[constants.dff_image_path])
    queries = tbx.split_pack(images, nb_per_split)

    list_files = []
    if nb_per_files:
        if not output_template:
                logger.error("Please restart pimmi query --nb-per-files with '--output-template' or do not use --nb-per-files.")
                sys.exit(1)
        else : 
            for i in range(math.ceil(len(images)/nb_per_files)):
                list_files.append(output_template+str(i)+".csv")
    else:
        if output :
            list_files.append(output)
        else :
            list_files.append(sys.stdout)  
        nb_per_files = len(images)

    while list_files != [] :
        pack_result_file = list_files[0]
        i=0
        while i < nb_per_files :
            for pack in queries : 
                if i+len(pack) > nb_per_files :
                    diff = i+len(pack)-nb_per_files
                    pack_to_add = pack[:diff]
                    pack_reste = pack[diff:]
                    queries.remove(pack)
                    query_result = query_index_mt(
                        index,
                        pack_to_add[constants.dff_pack_files],
                        image_dir,
                        pack=pack_to_add[constants.dff_pack_id]
                    )
                    if query_result:
                        query_result.to_csv(pack_result_file)
                    queries.append(pack_reste)
                    i = nb_per_files
                else: 
                    query_result = query_index_mt(
                        index,
                        pack[constants.dff_pack_files],
                        image_dir,
                        pack=pack[constants.dff_pack_id]
                    )
                    if query_result:
                        query_result.to_csv(pack_result_file)
                    i+=len(pack)

        del(list_files[0])

   

def clusters( index_dir, filename, output, algo, **kwargs):
    faiss_index, faiss_meta = index_dir+"/index.faiss", index_dir+"/index.meta"
    if type(filename) is str :
        if os.path.isfile(filename) and filename != None :
            mining_files = filename
        else :
            all_files = glob.glob(filename + "*")
            if all_files :
                mining_files = filename + "*"
            else :
                logger.error("The file does not exist")
                sys.exit(1)
    else :
        mining_files=""

    #si c pas un seul fichier filename*
    #mining_files_pattern = mining_files + "_*"
    generate_clusters(
        mining_files,
        faiss_meta,
        output,
        prm.nb_match_ransac,
        algo,
    )


def viz(clusters, output, **kwargs):
    from_clusters_to_viz(clusters, output)


def eval(file, predicted_column, truth_column, query_column=None, ignore_missing=False, csv=False, **kwargs):
    if os.path.exists(file):
        metrics = evaluate(file, truth_column, predicted_column, status_column=query_column, include_missing_predictions= not ignore_missing)
        if csv:
            print(",".join(str(round(m, 3)) for m in metrics.values()))
        else:
            for metric, value in metrics.items():
                print("{}: {}".format(metric, value))
    else:
        logger.error("{} file does not exist".format(file))

def make_index_path(index_dir, index_name, index_type):
    path = os.path.join(index_dir, ".".join([index_name, index_type]))
    return ".".join([path, "faiss"]), ".".join([path, "meta"])


def config_params(**kwargs):
    for param, value in config_dict.items():
        print("--{}: {}".format(param, value))


def create_config(path, **kwargs):
    shutil.copyfile(config_path, path)
    print("Created config file {}".format(path))


def load_custom_config(config_path):
    if os.path.isfile(config_path):
        logger.info("loading configuration from " + config_path)
        custom_config_dict = prm.load_config_file(config_path)
        for param, value in custom_config_dict.items():
            if type(value) == dict and "help" in value:
                value = value["value"]
            if hasattr(prm, param):
                #todo: use the parser to do this
                setattr(prm, param, value)
            else:
                raise AttributeError(param)
    else:
        logger.error("The provided config file does not exist.")
        sys.exit(1)


def check_custom_config(config_path):
    if config_path:
        try:
            load_custom_config(config_path)
        except AttributeError as wrong_param:
            print("pimmi: error: unrecognized argument in custom config file: {}. "
                  "Use pimmi config-params to display all existing parameters."
                  .format(wrong_param))
            parser.print_usage()
            sys.exit(1)


def confirm(question):
    print(question + " y/n")
    answer = input().lower().strip()
    if answer in ("y", "yes"):
        return True
    if answer in ("n", "no"):
        return False
    logger.error("Invalid input, please answer by 'y' or 'n'.")
    sys.exit(1)


def main():
    cli_params = load_cli_parameters()
    if cli_params["silent"]:
        logger.setLevel(level=logging.ERROR)
    if "func" in cli_params:
        config_path = cli_params.pop("config_path", None)
        check_custom_config(config_path)

        command = cli_params.pop("func")
        command(**cli_params)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
