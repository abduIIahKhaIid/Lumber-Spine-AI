# ----------------- Gated Attention Block (with Residual) -----------------
import timm
import torch.nn as nn


class GatedAttention(nn.Module):
    def __init__(self, in_features):
        super().__init__()
        self.gate = nn.Sequential(nn.Linear(in_features, in_features), nn.Sigmoid())

    def forward(self, x):
        gate = self.gate(x)
        return x * gate + x  # Residual connection


# ----------------- EfficientNetV2-S Spine Detection Model -----------------
class EfficientNetV2SCS(nn.Module):
    def __init__(self):
        super().__init__()

        # Load EfficientNetV2-S backbone
        self.encoder = timm.create_model(
            "efficientnetv2_s", pretrained=False, in_chans=3, features_only=False, num_classes=0
        )

        # Feature dimension
        self.in_features = self.encoder.num_features  # 1280 for EfficientNetV2-S

        # Adaptive Pooling + Flatten
        self.flatten = nn.Sequential(nn.AdaptiveAvgPool2d((1, 1)), nn.Flatten(1))

        # Gated Attention after encoder output
        self.attention = GatedAttention(self.in_features)

        # Project feature
        self.projector = nn.Identity()

        # Dropout for regularization
        self.dropout = nn.Dropout(p=0.2)

        # Heads for 5 vertebral levels
        self.heads = nn.ModuleList([nn.Linear(self.in_features, 2) for _ in range(5)])

    def forward(self, x):
        # Feature extraction
        x = self.encoder.forward_features(x)
        x = self.flatten(x)

        # Gated Attention
        x = self.attention(x)

        # Project to feature dimension
        x = self.projector(x)

        # Small dropout
        x = self.dropout(x)

        # Predict each level
        output = {}
        levels = ["L1/L2", "L2/L3", "L3/L4", "L4/L5", "L5/S1"]

        for i, level in enumerate(levels):
            output[level] = self.heads[i](x).sigmoid()

        return output


# ----------------- EfficientNetV2-S NFN Detection Model -----------------
class EfficientNetV2NFN(nn.Module):
    def __init__(self):
        super().__init__()

        # Load EfficientNetV2-S backbone
        self.encoder = timm.create_model(
            "efficientnetv2_s", in_chans=3, pretrained=False, features_only=False, num_classes=0
        )

        # Feature dimension
        self.in_features = self.encoder.num_features

        # Adaptive Pooling + Flatten
        self.flatten = nn.Sequential(nn.AdaptiveAvgPool2d((1, 1)), nn.Flatten(1))

        # Gated Attention after encoder output
        self.attention = GatedAttention(self.in_features)

        # Project feature (increased from 1024 to 1280 for improved representational capacity)
        self.projector = nn.Identity()

        # Dropout for regularization
        self.dropout = nn.Dropout(p=0.2)

        # Heads for 5 vertebral levels (left and right)
        self.ll1 = nn.Linear(self.in_features, 2)
        self.ll2 = nn.Linear(self.in_features, 2)
        self.ll3 = nn.Linear(self.in_features, 2)
        self.ll4 = nn.Linear(self.in_features, 2)
        self.ll5 = nn.Linear(self.in_features, 2)

        self.rl1 = nn.Linear(self.in_features, 2)
        self.rl2 = nn.Linear(self.in_features, 2)
        self.rl3 = nn.Linear(self.in_features, 2)
        self.rl4 = nn.Linear(self.in_features, 2)
        self.rl5 = nn.Linear(self.in_features, 2)

    def forward(self, x, label=None):
        # Reshape input to handle both left and right side images
        shape = x.shape
        x = x.reshape(shape[0] * shape[1], 3, shape[-2], shape[-1])  # Flatten the batch and side

        # Feature extraction through EfficientNetV2-S
        x = self.encoder.forward_features(x)
        x = self.flatten(x)
        x = x.reshape(shape[0], shape[1], -1)  # Split back into left and right

        # Split features for left and right
        x_left = x[:, 0, :]
        x_right = x[:, 1, :]

        # Apply Gated Attention
        x_left = self.attention(x_left)
        x_right = self.attention(x_right)

        # Project features into desired size
        x_left = self.projector(x_left)
        x_right = self.projector(x_right)

        # Apply Dropout
        x_left = self.dropout(x_left)
        x_right = self.dropout(x_right)

        # Predict each level for left and right sides
        output = {
            "left_L1/L2": self.ll1(x_left).sigmoid(),
            "left_L2/L3": self.ll2(x_left).sigmoid(),
            "left_L3/L4": self.ll3(x_left).sigmoid(),
            "left_L4/L5": self.ll4(x_left).sigmoid(),
            "left_L5/S1": self.ll5(x_left).sigmoid(),
            "right_L1/L2": self.rl1(x_right).sigmoid(),
            "right_L2/L3": self.rl2(x_right).sigmoid(),
            "right_L3/L4": self.rl3(x_right).sigmoid(),
            "right_L4/L5": self.rl4(x_right).sigmoid(),
            "right_L5/S1": self.rl5(x_right).sigmoid(),
        }

        return output


# ----------------- EfficientNetV2-S SS Detection Model -----------------
class EfficientNetV2SS(nn.Module):
    def __init__(self):
        super().__init__()

        # Load EfficientNetV2-S backbone
        self.encoder = timm.create_model(
            "efficientnetv2_s",
            in_chans=1,  # Change to 1 for grayscale input
            pretrained=False,
            features_only=False,
            num_classes=0,
        )

        # Feature dimension
        self.in_features = self.encoder.num_features

        # Adaptive Pooling + Flatten
        self.flatten = nn.Sequential(nn.AdaptiveAvgPool2d((1, 1)), nn.Flatten(1))

        # Gated Attention after encoder output
        self.attention = GatedAttention(self.in_features)

        # Project feature (increased from 1024 to 1280 for improved representational capacity)
        self.projector = nn.Identity()

        # Dropout for regularization
        self.dropout = nn.Dropout(p=0.2)

        # Linear layers for left and right heads
        self.left = nn.Linear(self.in_features, 2)  # 5 vertebral levels
        self.right = nn.Linear(self.in_features, 2)  # 5 vertebral levels

    def forward(self, x, label=None):
        # Reshape input to handle both left and right side images
        shape = x.shape
        x = x.reshape(shape[0] * shape[1], 1, shape[-2], shape[-1])  # Flatten the batch and side

        # Feature extraction through EfficientNetV2-S
        x = self.encoder.forward_features(x)
        x = self.flatten(x)
        x = x.reshape(shape[0], shape[1], -1)  # Split back into left and right

        # Split features for left and right
        x_left = x[:, :5, :]
        x_right = x[:, 5:, :]

        # Apply Gated Attention
        x_left = self.attention(x_left)
        x_right = self.attention(x_right)

        # Project features into desired size
        x_left = self.projector(x_left)
        x_right = self.projector(x_right)

        # Apply Dropout
        x_left = self.dropout(x_left)
        x_right = self.dropout(x_right)

        left = self.left(x_left)
        right = self.right(x_right)

        # Predict each level for left and right sides
        output = {
            "left_L1/L2": left[:, 0, :].sigmoid(),
            "left_L2/L3": left[:, 1, :].sigmoid(),
            "left_L3/L4": left[:, 2, :].sigmoid(),
            "left_L4/L5": left[:, 3, :].sigmoid(),
            "left_L5/S1": left[:, 4, :].sigmoid(),
            "right_L1/L2": right[:, 0, :].sigmoid(),
            "right_L2/L3": right[:, 1, :].sigmoid(),
            "right_L3/L4": right[:, 2, :].sigmoid(),
            "right_L4/L5": right[:, 3, :].sigmoid(),
            "right_L5/S1": right[:, 4, :].sigmoid(),
        }

        return output
