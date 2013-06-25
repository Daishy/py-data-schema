

from collections import OrderedDict

from .core import ContainerToken, Token
from .exceptions import SchemaError, ValidationError


__all__ = ['And', 'Or', 'Dict']



class And(ContainerToken):
	"""
	This token holds a range of other tokens which must all validate, if validation is called on
	this container
	"""

	def __init__(self, *args):
		super(And, self).__init__()
		self.compiled = [self.get_token(arg) for arg in args]

	def set_path(self, path):
		self.path = path + u"And->"
		for token in self.compiled:
			token.set_path(self.path)

	def validate(self, values):
		for token in self.compiled:
			values = token.validate(values)
		return values


	def __add__(self, other):
		""" Adding to and-tokens together. All entries of the first and are joined by the 
		second and entries. """
		if not isinstance(other, And):
			raise SchemaError(u"Can't combine none-and-token `{}` and and-token `{}`!".format(other, self))
		return And(*(self.compiled + other.compiled))

	def as_json(self, **kwargs):
		_tmp = {key: token.as_json() for key, token in self.compiled.items()}
		return super(Dict, self).as_json(name="And", **_tmp)



class Or(ContainerToken):
	"""
	This token holds a set of other tokens. If validate, the first token to successfully validate will be used.
	If no token can validate the input, a schema-error is raised
	"""

	def __init__(self, msg=None, *args):
		super(Or, self).__init__()
		self.msg = msg
		self.compiled = [self.get_token(arg) for arg in args]

	def set_path(self, path):
		self.path = path + "Or->"
		for token in self.compiled:
			token.set_path(self.path)

	def validate(self, values):
		for token in self.compiled:
			try:
				return token.validate(values)
			except SchemaError as e:
				pass

		return ValidationErrror(self.msg or u"Or-Token {} found no child-token that validates the input `{}`".format(self.path, values))

	def as_json(self, **kwargs):
		_tmp = {key: token.as_json() for key, token in self.compiled.items()}
		return super(Dict, self).as_json(name="Or", **_tmp)


	def __add__(self, other):
		"""
		Adding to or-tokens together. The resulting or will first check the values from the first and then from the second
		"""
		if not isinstance(other, Or):
			raise SchemaError(u"Can't combine none-Or-token `{}` and Or-token `{}`!".format(other, self))
		return Or(*(self.compiled + other.compiled))




class TypeKey(object):
	"""
	A typekey is used in the dict, if not a value (e.g. {"a": int}) is used, but a 
	type (e.g. {str: object})). TypeKeys have an ordering, where a more specific Key 
	is less then less specific one (bool < int < number), which gives more specific keys
	the chance to check their value first. 
	"""
	def __init__(self, key_type):
		self.key_type = key_type

	def matches(self, value_key):
		return isinstance(value_key, self.key_type)

	def __repr__(self):
		return u"<Dict.TypeKey {}>".format(self.key_type.__name__)

	def __cmp__(self, other):
		""" return -1 (smaller) if self is a child of other, else we dont care """
		return -1 if issubclass(self.key_type, other.key_type) else 0



class Dict(ContainerToken):
	""" 
	Holds a python-dictionary with a list of tokens and some other configurations. This class
	cant be instanciated directly, its only used in the internal representation.
	
	If allow_extra_keys is False (Default is False), the dict will validate only known keys 
	are within the struct to validate.
	
	This class is somewhat different from the other tokens. First of, it can only be instantited indireclty
	within the hirarchy, furthermore this does not register for a basic type, because the object
	is created a bit different (It gets the Sub-defintion of the python-dict)
	"""
	
	# Static objects for storing infos on the dict. object is used, to get a unique object to store in the dict
	default, skip_unknown_keys, desc, required = object(), object(), object(), object()
	
	
	def __init__(self, definition):
		"""
		Init the Dict with the given python-dict. This will extract the settings for the dict
		and all tokens expected
		"""

		super(Dict, self).__init__()

		# First extract all settings for the dict
		self.skip_unknown_keys = definition.pop(Dict.skip_unknown_keys, False)
		self.required = definition.pop(Dict.required, True)
		self.default = definition.pop(Dict.default, None)
		self.desc = definition.pop(Dict.desc, None)

		# As a first step get all keys, distinguish them and get the token
		self.compiled_valuekeys = {}
		self.compiled_typekeys = {}
	
		for key, value in definition.items():
			token = self.get_token(value)

			if isinstance(key, Token):
				raise NotImplementedError(u"This is currently not supported! Use basic types!")
			elif isinstance(key, type):
				self.compiled_typekeys[TypeKey(key)] = token
			else:
				self.compiled_valuekeys[key] = token
				
		
			

		# Now order the Typekey-dict with respect to their priority
		self.compiled_typekeys = OrderedDict(sorted(self.compiled_typekeys.items(), key=lambda t: t[0]))
		

	def set_path(self, path):
		self.path = path + "Dict"
		for key, token in self.compiled_valuekeys.items():
			token.set_path(u"{}:{}->".format(self.path, key))
		for key, token in self.compiled_typekeys.items():
			token.set_path(u"{}:{}->".format(self.path, key))

		
	def validate(self, value):
		"""
		Validate the dictionary. This will first iterate through the `compiled_valuekeys` and process each 
		entry with the matching entry in `value` (Keys that are not found in value will be validate with None as value.
		If the token wont allow that, a ValidationError is raised!)
		Next up, each entry that was not yet validated in values will be passed to the first handler in `compiled_typekeys`, 
		if there is a matching one. `validate` will be called on the found handler, with the entry in `value`.
		At last, if there are still unprocessed entries in value, we will check if that is allowed or not
		"""
		# we dont have data, so check if there is a default and if so, return that
		if value == None:
			if self.default == None and self.required:
				raise ValidationError(u"Value passed to {} should have values, but is None!".format(self.path))
			return self.default
			
		# check we have the right kind of data
		elif not isinstance(value, dict):
			raise ValidationError(u"Value passed to {} is not a dict! (value: {})".format(self.path, type(value)))

		# we have both data and is the right type, so validate it
		else:
			result = {}
			tmp = {k: v for k, v in value.items()} # Create a copy of the input, so the input is not changed

			
			# First validate each token found in the value-dict
			for key, token in self.compiled_valuekeys.items():
				result[key] = token.validate(tmp.pop(key, None))
			
			# Now try to match the compiled_typekeys to the left-over values (If match, validate and remove value)
			for key, value in tmp.items():
				for dictkeytype, token in self.compiled_typekeys.items():
					if dictkeytype.matches(key):
						result[key] = token.validate(value)
						del tmp[key]
						break

	

			# now just check if there are leftovers and if they are allowed. If so, add them 
			if not self.skip_unknown_keys and len(tmp) > 0:
				raise ValidationError(u"Dict '{}'' is fixed but encountered additional values: {}".format(self.path, tmp))

			# return the final dict
			return result

	
	
	def __add__(self, other):
		""" Unless most other tokens, two dicts can be combined into a new one. This can be used to merge to Schemas
		When combining two dicts, the settings from the first dict are used. Each key in both the dicts has to be unique. It
		is not possible for example to add {'a': int} to {'a': bool}. 
		This doesnt produce a deep copy. Only a new Dict-token is created, all other tokens are the same!
		"""
		if not isinstance(other, Dict):
			raise SchemaError(u"Tried to add non-dict ({}) to dict!".format(other))

		definition = {}

		
		# Adding tokes of self
		for key, token in self.compiled_valuekeys.items():
			definition[key] = token
		for key, token in self.compiled_typekeys.items():
			definition[key] = token

		# Update from other
		for key, token in other.compiled_valuekeys.items():
			if key in definition:
				raise SchemaError(u"Can't merge {} with {}, because of multiple key `{}`.".format(self, other, key))
			definition[key] = token
		
		for key, token in other.compiled_typekeys.items():
			if key in definition:
				raise SchemaError(u"Can't merge {} with {}, because of multiple key `{}`.".format(self, other, key))
			definition[key] = token
	
		# Add Settings from self and other (the resulting dict will have the stricter of each rules)
		definition[Dict.required] = self.required or other.required
		definition[Dict.skip_unknown_keys] = self.skip_unknown_keys and other.skip_unknown_keys
		definition[Dict.desc] = self.desc
		if self.default != None and other.default != None:
			raise SchemaError(u"Both Dict-tokens have defaults. Cant merge!")
		definition[Dict.default] = self.default or other.default
		
		return Dict(definition)
		
		
		
		
		
	def as_json(self, **kwargs):
		_tmp = {key: token.as_json() for key, token in self.compiled_valuekeys.items()}
		for key, token in self.compiled_typekeys.items():
			_tmp[key] = token.as_json()
		return super(Dict, self).as_json(name="dict", skip_unknown_keys=self.skip_unknown_keys, required=self.required, desc=self.desc, default=self.default, **_tmp)