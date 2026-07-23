import 'dart:io';

import 'package:flutter/widgets.dart';

bool localFileExists(String path) => File(path).existsSync();

ImageProvider<Object>? localFileImage(String path) => FileImage(File(path));

Object? localFile(String path) => File(path);
