"""Utils module containing generic functions that are useful for adding transcript expression-aware annotations."""
import logging
from typing import Callable, List, Optional, Tuple, Union

import hail as hl

logging.basicConfig(
    format="%(asctime)s (%(name)s %(lineno)s): %(message)s",
    datefmt="%m/%d/%Y %I:%M:%S %p",
)
logger = logging.getLogger("transcript_annotation_utils")
logger.setLevel(logging.INFO)


def summarize_transcript_expression(
    mt: hl.MatrixTable,
    transcript_expression_expr: Union[
        hl.expr.NumericExpression, str
    ] = "transcript_tpm",
    tissue_expr: Union[hl.expr.StringExpression, str] = "tissue",
    summary_agg_func: Optional[Callable] = None,
) -> hl.Table:
    """
    Summarize a transcript expression MatrixTable by transcript, gene, and tissue.

    The `summary_agg_func` argument allows the user to specify a Hail
    aggregation function to use to summarize the expression by tissue. By
    default, the median is used.

    The returned Table has a row annotation for each tissue containing the
    summarized tissue expression value.

    :param mt: MatrixTable of transcript (rows) expression quantifications (entry) by
        sample (columns).
    :param transcript_expression_expr: Entry expression indicating transcript expression
        quantification. Default is 'transcript_tpm'.
    :param tissue_expr: Column expression indicating tissue type. Default is 'tissue'.
    :param summary_agg_func: Optional aggregation function to use to summarize the
        transcript expression quantification by tissue. Example: `hl.agg.mean`.
        Default is None, which will use a median aggregation.
    :return: A Table of summarized transcript expression by tissue
    """
    if summary_agg_func is None:
        summary_agg_func = lambda x: hl.median(hl.agg.collect(x))

    if isinstance(transcript_expression_expr, str):
        transcript_expression_expr = mt[transcript_expression_expr]

    if isinstance(tissue_expr, str):
        tissue_expr = mt[tissue_expr]

    mt = mt.group_cols_by(tissue=tissue_expr).aggregate(
        tx=summary_agg_func(transcript_expression_expr)
    )
    ht = mt.rename({"tx": ""}).make_table().key_by("transcript_id", "gene_id")

    # Annotate with the proportion of expression of transcript to gene per tissue. The
    # returned Table has a row annotation for each tissue containing the summarized
    # tissue expression value.
    ht = ht.annotate(expression_proportion=get_expression_proportion(ht))
    ht = ht.select(
        **{
            t: hl.struct(
                transcript_expression=ht[t],
                expression_proportion=ht.expression_proportion[t],
            )
            for t in ht.expression_proportion
        }
    )

    return ht


def get_expression_proportion(ht: hl.Table) -> hl.expr.StructExpression:
    """
    Calculate the proportion of expression of transcript to gene per tissue.

    :param ht: Table of summarized transcript expression by tissue.
    :return: StructExpression containing the proportion of expression of transcript to
        gene per tissue.
    """
    tissues = list(ht.row_value)

    # Calculate the sum of transcript expression by gene per tissue.
    gene_ht = ht.group_by("gene_id").aggregate(
        **{tissue: hl.agg.sum(ht[tissue]) for tissue in tissues}
    )

    # Return the proportion of expression of transcript to gene per tissue.
    gene = gene_ht[ht.gene_id]
    return hl.struct(
        **{
            tissue: hl.utils.misc.divide_null(ht[tissue], gene[tissue])
            for tissue in tissues
        }
    )


def filter_expression_ht_by_tissues(
    ht: hl.Table,
    tissues_to_keep: Optional[List[str]] = None,
    tissues_to_filter: Optional[List[str]] = None,
) -> hl.Table:
    """
    Filter a Table with a row annotation for each tissue to only include specified tissues.

    :param ht: Table with a row annotation for each tissue.
    :param tissues_to_keep: Optional list of tissues to keep in the Table. Default is
        all non-key rows in the Table.
    :param tissues_to_filter: Optional list of tissues to exclude from the Table.
    :return: Table with only specified tissues.
    """
    if tissues_to_keep is None and tissues_to_filter is None:
        logger.info(
            "No tissues_to_keep or tissues_to_filter specified. Returning input Table."
        )
        return ht

    if tissues_to_keep is None:
        tissues = list(ht.row_value)

    if tissues_to_filter is not None:
        logger.info("Filtering tissues: %s", tissues_to_filter)
        tissues = [t for t in tissues if t not in tissues_to_filter]

    ht = ht.select(*tissues)

    return ht


def tissue_expression_ht_to_array(
    ht: hl.Table,
    tissues_to_keep: Optional[List[str]] = None,
    tissues_to_filter: Optional[List[str]] = None,
    annotations_to_extract: Optional[Union[Tuple[str], List[str]]] = (
        "transcript_expression",
        "expression_proportion",
    ),
) -> hl.Table:
    """
    Convert a Table with a row annotation for each tissue to a Table with tissues as an array.

    The output is a Table with one of the two formats: either an annotation of
    'tissue_expression' containing an array of structs by tissue, where each element of
    the array is the Table's row value for a given tissue, like this:
    # tissue_expression': array<struct {
    #     transcript_expression: float64,
    #     expression_proportion: float64
    # }>

    or a Table with one array annotation for each field defined in the
    'annotations_to_extract' argument, where each array is an array of the given field
    values by tissue, like this:
    # 'transcript_expression': array<float64>
    # 'expression_proportion': array<float64>

    The order of tissues in the array is indicated by the "tissues" global annotation.

    :param ht: Table with a row annotation for each tissue.
    :param tissues_to_keep: Optional list of tissues to keep in the tissue expression
        array. Default is all non-key rows in the Table.
    :param tissues_to_filter: Optional list of tissues to exclude from the
        tissue expression array.
    :param annotations_to_extract: Optional list of tissue struct fields to extract
        into top level array annotations. If None, the returned Table will contain a
        single top level annotation 'tissue_expression' that contains an array of
        structs by tissue. Default is ('transcript_expression', 'expression_proportion').
    :return: Table with requested tissue struct annotations pulled into arrays of
        tissue values and a 'tissues' global annotation indicating the order of tissues
        in the arrays.
    """
    ht = filter_expression_ht_by_tissues(ht, tissues_to_keep, tissues_to_filter)

    tissues = list(ht.row_value)
    ht = ht.select_globals(tissues=tissues)
    ht = ht.select(tissue_expression=[ht[t] for t in tissues])

    if annotations_to_extract is not None:
        ht = ht.select(
            **{
                a: ht.tissue_expression.map(lambda x: x[a])
                for a in annotations_to_extract
            }
        )

    return ht
