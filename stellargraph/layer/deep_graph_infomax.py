from . import GCN
from tensorflow.keras.layers import Input, Dense, Lambda, Layer
import tensorflow as tf
from tensorflow.keras import backend as K

__all__ = [
    "GCNInfoMax",
]


class Discriminator(Layer):
    """
    This Layer computes the Discriminator function for Deep Graph Infomax (https://arxiv.org/pdf/1809.10341.pdf).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def build(self, input_shapes):

        self.kernel = self.add_weight(
            shape=(input_shapes[0][1], input_shapes[0][1]),
            initializer="glorot_uniform",
            name="kernel",
            regularizer=None,
            constraint=None,
        )
        self.built = True

    def call(self, inputs):
        """
        Applies the layer to the inputs.

        Args:
            inputs: a list of tensors with shapes [(N, F), (F,)] containing the node features and summary feature
                vector.
        """
        features, summary = inputs

        score = tf.linalg.matvec(tf.linalg.matmul(features, self.kernel), summary,)

        return score


class GCNInfoMax(GCN):
    """
    A stack of Graph Convolutional layers that implement a Deep Graph Infomax model
    as in https://arxiv.org/pdf/1809.10341.pdf

    The model minimally requires specification of the layer sizes as a list of ints
    corresponding to the feature dimensions for each hidden layer,
    activation functions for each hidden layers, and a CorruptedFullBatchNodeGenerator object.

    To use this class as a Keras model, the features, shuffled features, and a pre-processed adjacency matrix
    should be supplied using the :class:`CorruptedFullBatchNodeGenerator` class for unsupervised training. After
    training, a model that returns the node embeddings can be obtained using the `GCNInfoMax.embedding_model` function.

    Args:
        layer_sizes (list of int): Output sizes of GCN layers in the stack.
        generator (FullBatchNodeGenerator): The generator instance.
        bias (bool): If True, a bias vector is learnt for each layer in the GCN model.
        dropout (float): Dropout rate applied to input features of each GCN layer.
        activations (list of str or func): Activations applied to each layer's output;
            defaults to ['relu', ..., 'relu'].
        kernel_initializer (str or func, optional): The initialiser to use for the weights of each layer.
        kernel_regularizer (str or func, optional): The regulariser to use for the weights of each layer.
        kernel_constraint (str or func, optional): The constraint to use for the weights of each layer.
        bias_initializer (str or func, optional): The initialiser to use for the bias of each layer.
        bias_regularizer (str or func, optional): The regulariser to use for the bias of each layer.
        bias_constraint (str or func, optional): The constraint to use for the bias of each layer.
    """

    def __init__(
        self,
        layer_sizes,
        generator,
        bias=True,
        dropout=0.0,
        activations=None,
        kernel_initializer=None,
        kernel_regularizer=None,
        kernel_constraint=None,
        bias_initializer=None,
        bias_regularizer=None,
        bias_constraint=None,
    ):

        super().__init__(
            layer_sizes,
            generator,
            bias=bias,
            dropout=dropout,
            activations=activations,
            kernel_initializer=kernel_initializer,
            kernel_regularizer=kernel_regularizer,
            kernel_constraint=kernel_constraint,
            bias_initializer=bias_initializer,
            bias_regularizer=bias_regularizer,
            bias_constraint=bias_constraint,
        )

    def unsupervised_node_model(self):
        """
        A function to create the the inputs and outputs for a Deep Graph Infomax model for unsupervised training.

        Returns:
            input and output layers for use with a keras model
        """
        # Inputs for features
        x_t = Input(batch_shape=(1, self.n_nodes, self.n_features))
        # Inputs for shuffled features
        x_corr = Input(batch_shape=(1, self.n_nodes, self.n_features))

        out_indices_t = Input(batch_shape=(1, None), dtype="int32")

        # Create inputs for sparse or dense matrices
        if self.use_sparse:
            # Placeholders for the sparse adjacency matrix
            A_indices_t = Input(batch_shape=(1, None, 2), dtype="int64")
            A_values_t = Input(batch_shape=(1, None))
            A_placeholders = [A_indices_t, A_values_t]

        else:
            # Placeholders for the dense adjacency matrix
            A_m = Input(batch_shape=(1, self.n_nodes, self.n_nodes))
            A_placeholders = [A_m]

        x_inp = [x_corr, x_t, out_indices_t] + A_placeholders

        node_feats = self([x_t, out_indices_t] + A_placeholders)
        node_feats = Lambda(lambda x: K.squeeze(x, axis=0,), name="NODE_FEATURES",)(
            node_feats
        )

        node_feats_corrupted = self([x_corr, out_indices_t] + A_placeholders)
        node_feats_corrupted = Lambda(lambda x: K.squeeze(x, axis=0,),)(
            node_feats_corrupted
        )

        summary = Lambda(lambda x: tf.math.sigmoid(tf.math.reduce_mean(x, axis=0)))(
            node_feats
        )

        discriminator = Discriminator()
        scores = discriminator([node_feats, summary])
        scores_corrupted = discriminator([node_feats_corrupted, summary])

        x_out = tf.stack([scores, scores_corrupted], axis=1)

        x_out = K.expand_dims(x_out, axis=0)
        return x_inp, x_out

    def embedding_model(self, model):
        """
        A function to create the the inputs and outputs for an embedding model.

        Args:
            model (keras.Model): the base Deep Graph Infomax model
        Returns:
            input and output layers for use with a keras model
        """
        x_emb_in = model.inputs
        x_emb_out = model.get_layer("NODE_FEATURES").output

        return x_emb_in, x_emb_out